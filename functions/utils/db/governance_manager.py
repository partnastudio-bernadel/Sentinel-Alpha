"""
Database Manager

Handles all database operations for IntentCore.
Migrated to MongoDB, utilizing the central get_db_client connection.
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from uuid import uuid4

# Setup paths to ensure we can import get_db_client
script_dir = os.path.dirname(os.path.abspath(__file__))
sentiment_dir = os.path.dirname(os.path.dirname(os.path.dirname(script_dir)))
if sentiment_dir not in sys.path:
    sys.path.insert(0, sentiment_dir)

from functions.utils.db.connect import get_db_client
from functions.models.reasoning_chain import ReasoningChain

logger = logging.getLogger(__name__)

class DatabaseManager:
    """
    Manages MongoDB database for IntentCore Governance.

    Handles:
    - governance_reasoning_chains: Audit trail of all agent decisions
    - governance_review_queue: Review queue of compliance items
    - governance_audit_logs: Detailed system audit logs
    """

    def __init__(self, db_path: str = None):
        """
        Initialize MongoDB database manager.
        (db_path is kept for backwards compatibility but ignored)
        """
        try:
            self.client, self.db_name = get_db_client()
            self.db = self.client[self.db_name]
            self.chains_col = self.db["governance_reasoning_chains"]
            self.queue_col = self.db["governance_review_queue"]
            self.audit_col = self.db["governance_audit_logs"]
            
            # Simple indexing
            self.chains_col.create_index("chain_id", unique=True)
            self.queue_col.create_index("queue_id", unique=True)
            self.queue_col.create_index("status")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")

    # ===== Reasoning Chain Operations =====

    def save_reasoning_chain(self, chain: ReasoningChain) -> str:
        """Save reasoning chain to MongoDB."""
        doc = {
            "chain_id": chain.chain_id,
            "timestamp": chain.timestamp,
            "agent_id": chain.agent_id,
            "agent_role": chain.agent_role,
            "task": chain.task,
            "conversation_history": chain.conversation_history,
            "situation": chain.situation,
            "quantitative_analysis": chain.quantitative_analysis,
            "options": chain.options,
            "selected_action": chain.selected_action,
            "rationale": chain.rationale,
            "risks": chain.risks,
            "completeness_score": chain.completeness_score,
            "missing_components": chain.missing_components,
            "policy_results": chain.policy_results,
            "requires_review": chain.requires_review,
            "governance_decision": chain.governance_decision,
            "reviewer_id": chain.reviewer_id,
            "review_timestamp": chain.review_timestamp,
            "human_decision": chain.human_decision,
            "human_rationale": chain.human_rationale,
            "human_modification": chain.human_modification,
            "execution_status": chain.execution_status,
            "execution_result": chain.execution_result,
            "execution_timestamp": chain.execution_timestamp,
            "pattern_id": chain.pattern_id,
            "template_id": chain.template_id,
            "confidence_score": chain.confidence_score
        }
        
        self.chains_col.update_one(
            {"chain_id": chain.chain_id},
            {"$set": doc},
            upsert=True
        )
        return chain.chain_id

    def get_reasoning_chain(self, chain_id: str) -> Optional[ReasoningChain]:
        """Get reasoning chain by ID."""
        doc = self.chains_col.find_one({"chain_id": chain_id})
        if not doc:
            return None
        return self._doc_to_reasoning_chain(doc)

    def update_reasoning_chain(self, chain: ReasoningChain):
        """Update existing reasoning chain."""
        self.save_reasoning_chain(chain)

    def query_reasoning_chains(
        self,
        agent_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        requires_review: Optional[bool] = None,
        limit: int = 100,
    ) -> List[ReasoningChain]:
        """Query reasoning chains with filters."""
        query = {}
        if agent_id:
            query["agent_id"] = agent_id
        
        if start_date or end_date:
            query["timestamp"] = {}
            if start_date:
                query["timestamp"]["$gte"] = start_date
            if end_date:
                query["timestamp"]["$lte"] = end_date
                
        if requires_review is not None:
            query["requires_review"] = requires_review
            
        docs = self.chains_col.find(query).sort("timestamp", -1).limit(limit)
        return [self._doc_to_reasoning_chain(doc) for doc in docs]

    def _doc_to_reasoning_chain(self, doc: Dict[str, Any]) -> ReasoningChain:
        """Convert MongoDB document to ReasoningChain object."""
        return ReasoningChain(
            chain_id=doc.get("chain_id"),
            timestamp=doc.get("timestamp"),
            agent_id=doc.get("agent_id"),
            agent_role=doc.get("agent_role"),
            task=doc.get("task"),
            conversation_history=doc.get("conversation_history", []),
            situation=doc.get("situation", ""),
            quantitative_analysis=doc.get("quantitative_analysis", {}),
            options=doc.get("options", []),
            selected_action=doc.get("selected_action", {}),
            rationale=doc.get("rationale", ""),
            risks=doc.get("risks", []),
            completeness_score=doc.get("completeness_score", 0.0),
            missing_components=doc.get("missing_components", []),
            policy_results=doc.get("policy_results", {}),
            requires_review=doc.get("requires_review", False),
            governance_decision=doc.get("governance_decision"),
            reviewer_id=doc.get("reviewer_id"),
            review_timestamp=doc.get("review_timestamp"),
            human_decision=doc.get("human_decision"),
            human_rationale=doc.get("human_rationale"),
            human_modification=doc.get("human_modification"),
            execution_status=doc.get("execution_status"),
            execution_result=doc.get("execution_result"),
            execution_timestamp=doc.get("execution_timestamp"),
            pattern_id=doc.get("pattern_id"),
            template_id=doc.get("template_id"),
            confidence_score=doc.get("confidence_score", 0.0)
        )

    # ===== Review Queue Operations =====

    def add_to_review_queue(
        self,
        chain_id: str,
        priority: str = "normal",
        assigned_to: Optional[str] = None,
    ) -> str:
        """Add reasoning chain to review queue."""
        queue_id = str(uuid4())
        priority_scores = {"urgent": 100, "high": 75, "normal": 50, "low": 25}
        
        doc = {
            "queue_id": queue_id,
            "chain_id": chain_id,
            "priority": priority,
            "priority_score": priority_scores.get(priority, 50),
            "assigned_to": assigned_to,
            "status": "pending",
            "queued_at": datetime.now(timezone.utc)
        }
        
        self.queue_col.insert_one(doc)
        return queue_id

    def get_pending_reviews(self, assigned_to: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get pending reviews from queue."""
        query = {"status": "pending"}
        if assigned_to:
            query["assigned_to"] = assigned_to
            
        docs = list(self.queue_col.find(query).sort("priority_score", -1))
        for d in docs:
            d["_id"] = str(d["_id"])
        return docs

    def complete_review(self, queue_id: str):
        """Mark review as completed."""
        self.queue_col.update_one(
            {"queue_id": queue_id},
            {"$set": {"status": "completed", "completed_at": datetime.now(timezone.utc)}}
        )

    # ===== Audit Log Operations =====

    def log_event(
        self,
        event_type: str,
        event_data: Dict[str, Any],
        chain_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ):
        """Log an event to audit trail."""
        doc = {
            "log_id": str(uuid4()),
            "timestamp": datetime.now(timezone.utc),
            "event_type": event_type,
            "event_data": event_data,
            "chain_id": chain_id,
            "user_id": user_id
        }
        self.audit_col.insert_one(doc)

    # ===== Metrics Operations =====

    def get_daily_metrics(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get daily metrics (mocked for MongoDB migration since not critical path)."""
        return []

    def get_summary_stats(self) -> Dict[str, Any]:
        """Get summary statistics."""
        total = self.chains_col.count_documents({})
        reviews = self.chains_col.count_documents({"requires_review": True})
        approved = self.chains_col.count_documents({"human_decision": "approved"})
        rejected = self.chains_col.count_documents({"human_decision": "rejected"})
        
        # Calculate avg completeness score
        pipeline = [
            {"$group": {"_id": None, "avg_completeness": {"$avg": "$completeness_score"}}}
        ]
        result = list(self.chains_col.aggregate(pipeline))
        avg = result[0]["avg_completeness"] if result else 0.0

        return {
            "total_decisions": total,
            "total_reviews": reviews,
            "total_approved": approved,
            "total_rejected": rejected,
            "avg_completeness": avg
        }
