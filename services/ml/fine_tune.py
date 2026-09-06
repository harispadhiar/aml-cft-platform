"""
AML/CFT Platform — Phase 2 QLoRA Fine-Tuning Script
=====================================================

This script fine-tunes a 7B–14B-class causal language model on a curated
synthetic SAR/STR gold dataset using QLoRA (Quantised Low-Rank Adaptation)
via the ``peft`` + ``bitsandbytes`` + ``trl`` stack.

Three fine-tuning tasks are covered by the training corpus:

1. **SAR Narrative Drafting**
   Given structured case data (customer profile, transaction pattern, screening
   hits), the model is trained to produce a fully-formed Suspicious Activity /
   Transaction Report narrative that conforms to FMU/SBP submission guidelines,
   including the 5W+H structure required by Pakistan's AML/CFT Regulations 2020.

2. **Red-Flag Classification**
   The model learns to label a transaction description with the most probable
   FATF/SBP typology flag (structuring, NACTA-hit, high-risk wire transfer,
   velocity anomaly, adverse media) and to state zero-tolerance false-negative
   policy: when in doubt, escalate.

3. **MLRO Summary Generation**
   Given a completed investigation file, the model drafts a concise MLRO
   (Money Laundering Reporting Officer) decision memo that summarises risk
   factors, recommended action (file STR / close case / escalate), and the
   regulatory basis for that recommendation.

GPU Infrastructure Note
-----------------------
This script is **intentionally not runnable on CPU-only machines**.
bitsandbytes 4-bit quantisation requires a CUDA GPU with ≥16 GB VRAM
(A100/A10G/H100 or equivalent).  The script exits gracefully with an
informative error if the optional GPU libraries are absent.

Typical invocation on an A100 node:
    python fine_tune.py \\
        --model_name mistralai/Mistral-7B-Instruct-v0.2 \\
        --dataset_path data/synthetic_sar_gold_dataset.jsonl \\
        --output_dir checkpoints/aml-cft-lora \\
        --epochs 3 \\
        --batch_size 4
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Logging setup — before any heavy imports so startup problems are visible.
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("aml_cft.fine_tune")

# ---------------------------------------------------------------------------
# Optional GPU-only imports — fail gracefully with actionable guidance.
# ---------------------------------------------------------------------------
_GPU_INSTALL_HINT = (
    "\n\n[INSTALL HINT] This script requires GPU infrastructure with CUDA ≥12.\n"
    "Install the required packages inside a GPU-enabled environment:\n\n"
    "    pip install 'torch>=2.2' --index-url https://download.pytorch.org/whl/cu121\n"
    "    pip install bitsandbytes>=0.43 peft>=0.10 trl>=0.8 transformers>=4.40 datasets>=2.18\n\n"
    "For cloud usage: launch an AWS p3.2xlarge / GCP a2-highgpu-1g / Azure NC24ads_A100_v4 instance\n"
    "and re-run this script there.  Local CPU execution is not supported.\n"
)

try:
    import torch
    import transformers
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        TrainingArguments,
    )
except ImportError as exc:
    logger.error("torch / transformers not found: %s%s", exc, _GPU_INSTALL_HINT)
    sys.exit(1)

try:
    import bitsandbytes  # noqa: F401 — side-effect import; presence check only
except ImportError as exc:
    logger.error(
        "bitsandbytes not installed (required for 4-bit quantisation): %s%s",
        exc,
        _GPU_INSTALL_HINT,
    )
    sys.exit(1)

try:
    from peft import LoraConfig, TaskType, get_peft_model, prepare_model_for_kbit_training
except ImportError as exc:
    logger.error("peft not installed (required for LoRA): %s%s", exc, _GPU_INSTALL_HINT)
    sys.exit(1)

try:
    from trl import SFTTrainer
except ImportError as exc:
    logger.error("trl not installed (required for SFTTrainer): %s%s", exc, _GPU_INSTALL_HINT)
    sys.exit(1)

try:
    from datasets import load_dataset
except ImportError as exc:
    logger.error("datasets not installed: %s%s", exc, _GPU_INSTALL_HINT)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_MODEL_NAME: str = "mistralai/Mistral-7B-Instruct-v0.2"
DEFAULT_DATASET_PATH: str = "data/synthetic_sar_gold_dataset.jsonl"
DEFAULT_OUTPUT_DIR: str = "checkpoints/aml-cft-lora"
DEFAULT_EPOCHS: int = 3
DEFAULT_BATCH_SIZE: int = 4
DEFAULT_GRAD_ACCUM: int = 4
DEFAULT_LR: float = 2e-4
DEFAULT_MAX_SEQ_LEN: int = 2048

# LoRA hyper-parameters (fixed per spec)
LORA_R: int = 16
LORA_ALPHA: int = 32
LORA_TARGET_MODULES: list[str] = ["q_proj", "v_proj"]
LORA_DROPOUT: float = 0.05


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    """Return the CLI argument parser for the fine-tuning script."""
    parser = argparse.ArgumentParser(
        prog="fine_tune.py",
        description=(
            "QLoRA fine-tuning for the AML/CFT LLM on the synthetic SAR gold dataset. "
            "Requires a CUDA GPU with ≥16 GB VRAM."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--model_name",
        type=str,
        default=DEFAULT_MODEL_NAME,
        help="HuggingFace model hub identifier or local path for the base causal LM.",
    )
    parser.add_argument(
        "--dataset_path",
        type=str,
        default=DEFAULT_DATASET_PATH,
        help="Path to the JSONL training dataset (relative to CWD or absolute).",
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where the LoRA adapter checkpoint is saved.",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=DEFAULT_EPOCHS,
        help="Number of full training epochs.",
    )
    parser.add_argument(
        "--batch_size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Per-device training batch size.",
    )
    parser.add_argument(
        "--grad_accum_steps",
        type=int,
        default=DEFAULT_GRAD_ACCUM,
        help="Gradient accumulation steps (effective_batch = batch_size × grad_accum_steps).",
    )
    parser.add_argument(
        "--lr",
        type=float,
        default=DEFAULT_LR,
        help="Peak learning rate for the AdamW optimiser.",
    )
    parser.add_argument(
        "--max_seq_length",
        type=int,
        default=DEFAULT_MAX_SEQ_LEN,
        help="Maximum tokenised sequence length; longer samples are truncated.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility.",
    )
    parser.add_argument(
        "--hf_token",
        type=str,
        default=None,
        help=(
            "HuggingFace access token for gated models (or set HF_TOKEN env var). "
            "Required for Mistral gated checkpoints."
        ),
    )
    return parser


# ---------------------------------------------------------------------------
# Dataset helpers
# ---------------------------------------------------------------------------

def _format_prompt(example: dict) -> dict:
    """
    Convert a raw JSONL record into a single ``text`` field suitable for SFT.

    The prompt follows the Mistral [INST] chat template so the fine-tuned
    adapter can be used directly via the Mistral chat API without further
    wrapping.  The assistant turn is the pre-written gold narrative, giving
    the model a faithful SAR drafting target.

    Parameters
    ----------
    example:
        A single record from ``synthetic_sar_gold_dataset.jsonl`` containing
        at minimum ``case_id`` and ``narrative`` keys.

    Returns
    -------
    dict
        A dictionary with a single ``text`` key holding the formatted prompt.
    """
    case_id: str = example.get("case_id", "UNKNOWN")
    customer_id: str = example.get("customer_id", "UNKNOWN")
    cnic: str = example.get("cnic", "UNKNOWN")
    narrative: str = example.get("narrative", "")

    user_turn = (
        f"You are an AML/CFT compliance assistant for a Pakistani financial institution.\n\n"
        f"Case Reference: {case_id}\n"
        f"Customer ID: {customer_id}\n"
        f"CNIC: {cnic}\n\n"
        f"Draft a complete Suspicious Activity Report (SAR/STR) narrative for this case, "
        f"following the 5W+H structure required by SBP AML/CFT Regulations 2020. "
        f"Cite all applicable regulations and typologies."
    )

    # Mistral [INST] format: <s>[INST] user [/INST] assistant </s>
    text = f"<s>[INST] {user_turn} [/INST] {narrative} </s>"
    return {"text": text}


def load_and_prepare_dataset(
    dataset_path: str,
    seed: int = 42,
) -> "datasets.Dataset":  # type: ignore[name-defined]
    """
    Load the JSONL dataset, apply prompt formatting, and split into train/eval.

    An 80/20 train–eval split is applied deterministically.  The eval split
    is used only for logging eval loss during training; the hold-out set used
    by ``eval_harness.py`` is kept entirely separate.

    Parameters
    ----------
    dataset_path:
        Absolute or CWD-relative path to the ``.jsonl`` file.
    seed:
        Random seed forwarded to the shuffle & split calls.

    Returns
    -------
    datasets.DatasetDict
        A ``DatasetDict`` with ``"train"`` and ``"test"`` splits.
    """
    path = Path(dataset_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Dataset not found: {path.resolve()}\n"
            "Run the data generation script first:\n"
            "  python scripts/generate_synthetic_data.py"
        )

    logger.info("Loading dataset from: %s", path.resolve())
    raw = load_dataset("json", data_files=str(path), split="train")
    logger.info("Loaded %d records.", len(raw))

    formatted = raw.map(_format_prompt, remove_columns=raw.column_names)
    split = formatted.train_test_split(test_size=0.2, seed=seed)
    logger.info(
        "Split: %d train / %d eval samples.", len(split["train"]), len(split["test"])
    )
    return split


# ---------------------------------------------------------------------------
# Model + tokeniser setup
# ---------------------------------------------------------------------------

def load_quantised_model(
    model_name: str,
    hf_token: Optional[str] = None,
) -> tuple["AutoModelForCausalLM", "AutoTokenizer"]:  # type: ignore[name-defined]
    """
    Load the base causal LM in 4-bit NF4 quantisation via bitsandbytes.

    The ``BitsAndBytesConfig`` is configured for double-quantisation which
    reduces VRAM overhead by ~25% at negligible accuracy cost, allowing a
    7B model to train comfortably on 16 GB VRAM cards.

    Parameters
    ----------
    model_name:
        HuggingFace Hub model identifier, e.g. ``"mistralai/Mistral-7B-Instruct-v0.2"``.
    hf_token:
        Optional HuggingFace access token.  Falls back to the ``HF_TOKEN``
        environment variable if not supplied.

    Returns
    -------
    tuple[AutoModelForCausalLM, AutoTokenizer]
        The quantised model and its matching tokeniser, both ready for use.
    """
    token: Optional[str] = hf_token or os.environ.get("HF_TOKEN")

    if not torch.cuda.is_available():
        raise RuntimeError(
            "No CUDA device detected.  QLoRA fine-tuning requires a GPU. "
            "Ensure this script is run on a CUDA-enabled machine."
        )

    gpu_name = torch.cuda.get_device_name(0)
    vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
    logger.info("GPU detected: %s (%.1f GB VRAM)", gpu_name, vram_gb)

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",          # Normal Float 4 — best for LLM weights
        bnb_4bit_compute_dtype=torch.bfloat16,  # bfloat16 forward pass for numerical stability
        bnb_4bit_use_double_quant=True,     # Nested quantisation reduces VRAM further
    )
    logger.info("Loading base model in 4-bit NF4 quantisation: %s", model_name)

    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        quantization_config=bnb_config,
        device_map="auto",                  # Automatic multi-GPU sharding if available
        trust_remote_code=False,
        token=token,
        torch_dtype=torch.bfloat16,
    )
    model.config.use_cache = False          # Required for gradient checkpointing
    model.config.pretraining_tp = 1         # Disable tensor parallelism from pretraining

    tokeniser = AutoTokenizer.from_pretrained(
        model_name,
        token=token,
        trust_remote_code=False,
    )
    # Mistral tokeniser has no padding token by default
    if tokeniser.pad_token is None:
        tokeniser.pad_token = tokeniser.eos_token
    tokeniser.padding_side = "right"        # Required for causal LM batching

    logger.info("Tokeniser pad_token set to: %r", tokeniser.pad_token)
    return model, tokeniser


# ---------------------------------------------------------------------------
# LoRA wrapping
# ---------------------------------------------------------------------------

def apply_lora(model: "AutoModelForCausalLM") -> "AutoModelForCausalLM":  # type: ignore[name-defined]
    """
    Wrap the quantised base model with LoRA adapters via ``peft``.

    Only the attention projection matrices (q_proj, v_proj) are updated during
    training.  This targets the components most responsible for attending to
    compliance-relevant tokens while keeping the adapter small (~8 M params).

    Parameters
    ----------
    model:
        The 4-bit quantised base model returned by :func:`load_quantised_model`.

    Returns
    -------
    AutoModelForCausalLM
        The model wrapped with trainable LoRA adapter layers.
    """
    model = prepare_model_for_kbit_training(model)

    lora_config = LoraConfig(
        r=LORA_R,                           # Rank: controls adapter expressiveness
        lora_alpha=LORA_ALPHA,              # Scaling factor (alpha/r = 2.0 here)
        target_modules=LORA_TARGET_MODULES, # q_proj + v_proj only
        lora_dropout=LORA_DROPOUT,
        bias="none",                        # Do not train bias terms
        task_type=TaskType.CAUSAL_LM,
    )

    model = get_peft_model(model, lora_config)
    trainable, total = model.get_nb_trainable_parameters()
    logger.info(
        "LoRA applied: %d trainable params / %d total (%.2f%% trainable)",
        trainable,
        total,
        100 * trainable / total,
    )
    return model


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def run_training(
    model: "AutoModelForCausalLM",  # type: ignore[name-defined]
    tokeniser: "AutoTokenizer",      # type: ignore[name-defined]
    dataset_split: "datasets.DatasetDict",  # type: ignore[name-defined]
    output_dir: str,
    epochs: int,
    batch_size: int,
    grad_accum_steps: int,
    lr: float,
    max_seq_length: int,
    seed: int,
) -> None:
    """
    Configure and run :class:`trl.SFTTrainer` on the formatted SAR dataset.

    Checkpoints are saved every 100 steps and at the end of each epoch.
    The final LoRA adapter (not full model weights) is written to ``output_dir``.

    Parameters
    ----------
    model:
        LoRA-wrapped quantised model.
    tokeniser:
        Matching tokeniser with pad_token configured.
    dataset_split:
        DatasetDict with ``"train"`` and ``"test"`` splits, each containing
        a ``"text"`` column of formatted prompt strings.
    output_dir:
        Destination directory for the adapter checkpoint.
    epochs:
        Number of training epochs.
    batch_size:
        Per-device batch size.
    grad_accum_steps:
        Gradient accumulation steps.
    lr:
        Peak AdamW learning rate.
    max_seq_length:
        Maximum token sequence length (longer samples are truncated).
    seed:
        Random seed for the trainer.
    """
    os.makedirs(output_dir, exist_ok=True)

    import inspect

    use_bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    use_fp16 = not use_bf16

    # Newer trl releases moved dataset_text_field/max_seq_length/packing off of
    # SFTTrainer and onto SFTConfig (a TrainingArguments subclass). Older trl
    # releases don't have SFTConfig at all and expect those kwargs directly on
    # SFTTrainer. We detect which API is installed at runtime instead of
    # hard-coding one, so this keeps working across trl upgrades.
    try:
        from trl import SFTConfig
        args_cls = SFTConfig
    except ImportError:
        SFTConfig = None
        args_cls = TrainingArguments

    common_training_kwargs = dict(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=max(1, batch_size // 2),
        gradient_accumulation_steps=grad_accum_steps,
        learning_rate=lr,
        lr_scheduler_type="cosine",
        warmup_steps=10,
        optim="paged_adamw_32bit",          # Memory-efficient paged AdamW for QLoRA
        bf16=use_bf16,
        fp16=use_fp16,
        logging_steps=25,
        save_strategy="steps",
        save_steps=100,
        save_total_limit=3,
        load_best_model_at_end=False,       # Adapter-only save; no full model reload
        report_to="none",                   # Disable wandb/mlflow for air-gapped envs
        seed=seed,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        ddp_find_unused_parameters=False,
    )

    args_params = inspect.signature(args_cls.__init__).parameters
    if "eval_strategy" in args_params:
        common_training_kwargs["eval_strategy"] = "epoch"
    elif "evaluation_strategy" in args_params:
        common_training_kwargs["evaluation_strategy"] = "epoch"

    # If we're on an SFTConfig-based trl, the dataset/formatting options live
    # here; field names have also shifted (max_seq_length -> max_length) across
    # trl versions, so check both.
    if SFTConfig is not None:
        if "dataset_text_field" in args_params:
            common_training_kwargs["dataset_text_field"] = "text"
        if "max_seq_length" in args_params:
            common_training_kwargs["max_seq_length"] = max_seq_length
        elif "max_length" in args_params:
            common_training_kwargs["max_length"] = max_seq_length
        if "packing" in args_params:
            common_training_kwargs["packing"] = False

    training_args = args_cls(**common_training_kwargs)

    sft_kwargs = {
        "model": model,
        "train_dataset": dataset_split["train"],
        "eval_dataset": dataset_split["test"],
        "args": training_args,
    }
    sft_params = inspect.signature(SFTTrainer.__init__).parameters
    if "processing_class" in sft_params:
        sft_kwargs["processing_class"] = tokeniser
    else:
        sft_kwargs["tokenizer"] = tokeniser

    # Only pass these directly to SFTTrainer if this trl version's SFTTrainer
    # still accepts them (i.e. we're on the older, pre-SFTConfig API).
    if SFTConfig is None:
        if "dataset_text_field" in sft_params:
            sft_kwargs["dataset_text_field"] = "text"
        if "max_seq_length" in sft_params:
            sft_kwargs["max_seq_length"] = max_seq_length
        if "packing" in sft_params:
            sft_kwargs["packing"] = False

    trainer = SFTTrainer(**sft_kwargs)

    logger.info(
        "Starting training: %d epochs | lr=%.1e | batch=%d | grad_accum=%d | max_seq=%d",
        epochs, lr, batch_size, grad_accum_steps, max_seq_length,
    )
    trainer.train()

    logger.info("Saving LoRA adapter to: %s", output_dir)
    trainer.model.save_pretrained(output_dir)
    tokeniser.save_pretrained(output_dir)
    logger.info("Fine-tuning complete.  Adapter saved.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse CLI arguments and orchestrate the full QLoRA fine-tuning pipeline."""
    parser = build_arg_parser()
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("AML/CFT QLoRA Fine-Tuning — Phase 2")
    logger.info("=" * 60)
    logger.info("Model  : %s", args.model_name)
    logger.info("Dataset: %s", args.dataset_path)
    logger.info("Output : %s", args.output_dir)
    logger.info("Epochs : %d", args.epochs)
    logger.info("Batch  : %d (× %d accum = %d effective)", args.batch_size, args.grad_accum_steps, args.batch_size * args.grad_accum_steps)
    logger.info("LR     : %.1e", args.lr)
    logger.info("=" * 60)

    # 1. Dataset
    dataset_split = load_and_prepare_dataset(args.dataset_path, seed=args.seed)

    # 2. Quantised base model
    model, tokeniser = load_quantised_model(args.model_name, hf_token=args.hf_token)

    # 3. LoRA wrapping
    model = apply_lora(model)

    # 4. Training
    run_training(
        model=model,
        tokeniser=tokeniser,
        dataset_split=dataset_split,
        output_dir=args.output_dir,
        epochs=args.epochs,
        batch_size=args.batch_size,
        grad_accum_steps=args.grad_accum_steps,
        lr=args.lr,
        max_seq_length=args.max_seq_length,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()