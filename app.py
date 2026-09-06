"""
Root entrypoint for Hugging Face Spaces or local launch.
Runs the AML/CFT Gradio Platform.
"""
from ui.gradio_app import demo, AUDIT_LOG_FILE, append_audit_entry

if __name__ == "__main__":
    if not AUDIT_LOG_FILE.is_file():
        append_audit_entry({"action": "GENESIS_INITIALIZATION", "system": "AML-CFT-PLATFORM"})

    demo.launch(
        server_name="127.0.0.1",
        server_port=7860,
        share=True
    )
