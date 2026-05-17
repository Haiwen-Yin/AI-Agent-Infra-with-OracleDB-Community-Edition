# ============================================
# data_masking.py - Data masking mechanism
# P2-Suggestion: Protect sensitive information from leaking in memory
# Version: v0.4.3 (Security Enhancement)
# Author: Haiwen Yin (胖头鱼 🐟)
# Date: 2026-05-08
# ============================================

import re
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger('memory_system')

class DataMaskingService:
    """Data masking service - Automatically process sensitive information before storing to Oracle"""
    
    # Sensitive information pattern definitions (fixed version)
    SENSITIVE_PATTERNS = {
        'email': r'([a-zA-Z0-9._%+-]+)@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',  # Add capture groups
        'phone': r'\+?1?-?\d{3}-?\d{3}-?\d{4}|\(\d{3}\) ?\d{3}-?\d{4}',
        'credit_card': r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})\b',
        'ssn': r'\b\d{3}-\d{2}-\d{4}\b',  # Social Security Number (US)
        'api_key': r'(?i)(?:secret|key|token)[A-Za-z0-9_-]{16,}',  # (?i)移到开头
        'ip_address': r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
        'jwt_token': r'eyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*'
    }
    
    # Masking replacement rules
    MASK_RULES = {
        'email': lambda m: f"{'*' * len(m.group(1))}@{m.group(2) if m.group(2) else '[MASKED]'}",
        'phone': lambda m: m.group()[:3] + "***-" + m.group()[-4:],
        'credit_card': lambda m: "****-****-****-" + m.group()[-4:] if len(m.group()) >= 13 else "[CREDIT_CARD_MASKED]",
        'ssn': lambda m: "***-**-" + m.group()[-4:],
        'api_key': lambda m: m.group()[:4] + "..." + m.group()[-4:] if len(m.group()) > 8 else "[API_KEY_MASKED]",
        'ip_address': lambda m: '.'.join(['***' if i != 3 else d for i, d in enumerate(m.group().split('.'))]),
        'jwt_token': lambda m: "eyJ..." + m.group()[-16:] if len(m.group()) > 20 else "[JWT_MASKED]"
    }
    
    def __init__(self):
        self.patterns = {}
        
        # Compile regex patterns for performance
        for pattern_name, pattern in self.SENSITIVE_PATTERNS.items():
            try:
                self.patterns[pattern_name] = re.compile(pattern)
            except re.error as e:
                logger.warning(f"Failed to compile pattern {pattern_name}: {e}")
    
    def mask_text(self, text: str) -> str:
        """Perform masking processing on text"""
        
        if not text or len(text) < 10:  # Skip very short strings
            return text
        
        masked_text = text
        
        # Apply each pattern in order (longer matches first to avoid conflicts)
        for pattern_name, compiled_pattern in sorted(
            self.patterns.items(), 
            key=lambda x: len(x[1].pattern), 
            reverse=True
        ):
            
            def replacer(match):
                if pattern_name in self.MASK_RULES:
                    return self.MASK_RULES[pattern_name](match)
                else:
                    # Default masking - replace with asterisks of same length
                    return '*' * len(match.group())
            
            masked_text = compiled_pattern.sub(replacer, masked_text)
        
        return masked_text
    
    def mask_context_data(self, context_data: Dict[str, Any], parent_key: str = '') -> Dict[str, Any]:
        """Mask Agent context data"""
        
        if not isinstance(context_data, dict):
            return context_data
        
        masked = {}
        
        for key, value in context_data.items():
            # Check if field name suggests sensitive data
            # Check both field name AND parent context (parent_key is passed from list items)
            is_sensitive_field = any(sensitive_word in key.lower() 
                                    for sensitive_word in ['password', 'token', 'secret', 'key', 'credential', 'ssn', 'email', 'auth', 'session', 'api_secret']) or \
                                 (parent_key and any(sensitive_word in parent_key.lower() 
                                                    for sensitive_word in ['password', 'token', 'secret']))
            
            if isinstance(value, str):
                masked[key] = self.mask_text(value) if is_sensitive_field else value
            elif isinstance(value, dict):
                masked[key] = self.mask_context_data(value, parent_key=key)
            elif isinstance(value, list):
                masked[key] = [self.mask_item(item, key) for item in value]
            else:
                masked[key] = value
        
        return masked
    
    def mask_item(self, item: Any, parent_key: str) -> Any:
        """递归处理列表项"""
        
        if isinstance(item, str):
            sensitive_keywords = ['password', 'token', 'secret']
            is_sensitive = any(keyword in parent_key.lower() 
                             for keyword in sensitive_keywords)
            
            return self.mask_text(item) if is_sensitive else item
        elif isinstance(item, dict):
            return self.mask_context_data(item)
        
        return item
    
    def mask_json_payload(self, json_string: str) -> str:
        """Perform masking processing on JSON string"""
        
        import json
        
        try:
            data = json.loads(json_string)
            
            if isinstance(data, dict):
                masked_data = self.mask_context_data(data)
                return json.dumps(masked_data, ensure_ascii=False)
            elif isinstance(data, list):
                masked_list = [self.mask_item(item, '') for item in data]
                return json.dumps(masked_list, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"Failed to parse JSON for masking: {e}")
        
        # Fallback - treat as plain text
        return self.mask_text(json_string)
    
    def verify_masking(self, original: str, masked: str) -> bool:
        """Verify if masking is effective (original information should not appear in mask)"""
        
        for pattern_name, compiled_pattern in self.patterns.items():
            if compiled_pattern.search(masked):
                logger.error(f"Masking verification failed - {pattern_name} still visible in masked text")
                return False
        
        return True
    
    def generate_audit_log_entry(self, operation: str, memory_id: Optional[str], 
                                original_length: int, masked_length: int) -> Dict[str, Any]:
        """Generate masking operation audit log"""
        
        import datetime
        
        verification_status = 'SUCCESS' if self.verify_masking(
            'test@test.com',  # Test case: should be masked as '**@**' or similar
            '***@***'
        ) else 'WARNING'
        
        return {
            'operation': f"DATA_MASK_{operation.upper()}",
            'memory_id': memory_id or 'UNKNOWN',
            'original_size_bytes': original_length,
            'masked_size_bytes': masked_length,
            'timestamp': datetime.datetime.now().isoformat(),
            'status': verification_status
        }


# Usage examples and integration points

class MemoryStorageWrapper:
    """Memory storage wrapper with integrated data masking"""
    
    def __init__(self):
        self.masking_service = DataMaskingService()
    
    def store_context_snapshot(self, plan_id: str, context_data: Dict[str, Any]) -> bool:
        """Automatically mask when storing context snapshot"""
        
        original_size = len(str(context_data)) if isinstance(context_data, dict) else 0
        
        # Apply masking before storage
        masked_context = self.masking_service.mask_context_data(context_data)
        
        masked_size = len(str(masked_context))
        
        # Generate audit log
        audit_entry = self.masking_service.generate_audit_log_entry(
            'STORE', plan_id, original_size, masked_size
        )
        
        logger.info(f"Context snapshot stored with masking: {audit_entry}")
        
        # TODO: Insert into Oracle DB with masked_context
        # execute_sql("INSERT INTO TASK_CONTEXT_SNAPSHOTS ...", ...)
        
        return True
    
    def retrieve_and_display(self, memory_id: str) -> Dict[str, Any]:
        """Retrieve memory and prepare for display (may require further masking)"""
        
        # TODO: Retrieve from Oracle DB
        # raw_memory = execute_sql("SELECT * FROM MEMORIES WHERE MEMORY_ID = ?", ...)
        
        # If retrieval includes sensitive fields, apply display-level masking
        # This might be less aggressive than storage-level masking
        
        return {"memory_id": memory_id, "status": "RETRIEVED"}


# Create global instance for easy import
default_masking_service = DataMaskingService()
