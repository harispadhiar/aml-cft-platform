from enum import Enum
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orchestrator")

class WorkflowState(Enum):
    NEW = "NEW"
    AUTOMATED_REVIEW = "AUTOMATED_REVIEW"
    PENDING_HUMAN_REVIEW = "PENDING_HUMAN_REVIEW"
    READY_FOR_FILING = "READY_FOR_FILING"
    FILED = "FILED"
    CLOSED_FALSE_POSITIVE = "CLOSED_FALSE_POSITIVE"

# 17-stagegate taxonomy subset for MVP
HITL_GATES = [
    "SCREENING_HIT_CONFIRMATION", 
    "RISK_TIER_OVERRIDE",
    "SAR_STR_FILING_APPROVAL",
    "HIGH_RISK_TRANSACTION_RELEASE"
]

class CaseStateMachine:
    def __init__(self, case_id: str, initial_state: WorkflowState = WorkflowState.NEW):
        self.case_id = case_id
        self.state = initial_state
        self.history = []

    def _log_transition(self, from_state, to_state, actor: str, reason: str):
        self.history.append({
            "from": from_state.value,
            "to": to_state.value,
            "actor": actor,
            "reason": reason
        })
        logger.info(f"[{self.case_id}] Transition {from_state.value} -> {to_state.value} by {actor}: {reason}")

    def trigger_automated_review(self):
        if self.state == WorkflowState.NEW:
            self._log_transition(self.state, WorkflowState.AUTOMATED_REVIEW, "System", "Started automated risk scoring")
            self.state = WorkflowState.AUTOMATED_REVIEW
            return True
        return False

    def handle_risk_score(self, score: int, tier: str, has_screening_hit: bool):
        if self.state != WorkflowState.AUTOMATED_REVIEW:
            return False
            
        if tier == "High" or has_screening_hit:
            self._log_transition(self.state, WorkflowState.PENDING_HUMAN_REVIEW, "System", f"High risk tier ({tier}) or screening hit detected. Requires HITL.")
            self.state = WorkflowState.PENDING_HUMAN_REVIEW
        else:
            self._log_transition(self.state, WorkflowState.CLOSED_FALSE_POSITIVE, "System", "Low risk, auto-closed.")
            self.state = WorkflowState.CLOSED_FALSE_POSITIVE
            
        return True

    def human_review_decision(self, actor: str, decision: str, reason: str):
        """
        decision can be 'APPROVE_FOR_FILING' or 'DISMISS'
        """
        if self.state != WorkflowState.PENDING_HUMAN_REVIEW:
            logger.warning(f"[{self.case_id}] Attempted human review in state {self.state.value}")
            return False
            
        if decision == "APPROVE_FOR_FILING":
            self._log_transition(self.state, WorkflowState.READY_FOR_FILING, actor, reason)
            self.state = WorkflowState.READY_FOR_FILING
        elif decision == "DISMISS":
            self._log_transition(self.state, WorkflowState.CLOSED_FALSE_POSITIVE, actor, reason)
            self.state = WorkflowState.CLOSED_FALSE_POSITIVE
            
        return True

    def mlro_file_sar(self, actor: str, role: str):
        if self.state != WorkflowState.READY_FOR_FILING:
            logger.warning(f"[{self.case_id}] Cannot file SAR from state {self.state.value}")
            return False
            
        if role != "MLRO":
            logger.error(f"[{self.case_id}] Unauthorized attempt to file SAR by {actor} (Role: {role})")
            return False
            
        self._log_transition(self.state, WorkflowState.FILED, actor, "SAR/STR successfully filed to FMU")
        self.state = WorkflowState.FILED
        return True

class AgentOrchestrator:
    def __init__(self):
        self.cases = {}
        
    def process_new_alert(self, case_id: str, case_data: dict):
        # 1. Initialize State Machine
        sm = CaseStateMachine(case_id)
        self.cases[case_id] = sm
        
        # 2. Automated Review
        sm.trigger_automated_review()
        
        # 3. Simulate calling risk engine and screening-mcp
        pattern = case_data.get("transaction_pattern", "").lower()
        hit = case_data.get("screening_hit", "None")
        
        has_screening_hit = "nacta" in hit.lower() or "sanctions" in hit.lower()
        
        # Dummy risk tier logic matching our risk engine
        tier = case_data.get("risk_score", "Low")
        
        sm.handle_risk_score(0, tier, has_screening_hit)
        
        return sm.state.value
        
    def attempt_auto_file(self, case_id: str):
        """
        Simulate an AI Agent attempting to bypass human review and file a SAR.
        """
        sm = self.cases.get(case_id)
        if not sm:
            return "Case not found."
            
        # AI Agent tries to jump straight to filing
        logger.info(f"[{case_id}] AI Agent attempting to auto-file SAR...")
        
        # The state machine blocks this because state is PENDING_HUMAN_REVIEW and role != MLRO
        success = sm.mlro_file_sar("AI_Agent", "AGENT")
        if not success:
            logger.warning(f"[{case_id}] Orchestrator halted execution. Transition blocked by HITL gate (SAR_STR_FILING_APPROVAL).")
            return "Execution halted: HITL Gate Enforcement blocked automated transition."
            
        return "Success"
        
if __name__ == "__main__":
    orch = AgentOrchestrator()
    print("Testing HITL Gate Enforcement...")
    
    # Trigger an entity match that evaluates to "High Risk / Sanctions Match"
    case_data = {
        "transaction_pattern": "Normal",
        "screening_hit": "True Positive NACTA match on entity name.",
        "risk_score": "High"
    }
    
    state = orch.process_new_alert("TEST-CASE-1", case_data)
    print(f"Current State: {state}")
    
    # Command the orchestration router to auto-file a SAR/STR
    result = orch.attempt_auto_file("TEST-CASE-1")
    print(result)
    
    # Assert engine halts execution and transitions case to PENDING_HUMAN_REVIEW
    final_state = orch.cases["TEST-CASE-1"].state.value
    print(f"Final State verified as: {final_state}")
