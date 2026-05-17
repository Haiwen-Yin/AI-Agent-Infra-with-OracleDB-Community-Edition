# ============================================
# context_aware_masking.py - Context-aware desensitization
# P2-Suggestion: Automatically select masking level based on usage scenario
# Version: v0.4.3 (Context-Aware)
# Author: Haiwen Yin (胖头鱼 🐟)
# Date: 2026-05-08
# ============================================

from enum import Enum
from typing import Optional, Dict, Any, List
import logging

logger = logging.getLogger('memory_system')


class DesensitizationLevel(Enum):
    """Desensitization level enumeration"""
    LOGGING = "LOGGING"      # HIGH - Logging and monitoring: full masking
    DEBUGGING = "DEBUGGING"  # MEDIUM - Debug mode: partial retention
    ANALYTICS = "ANALYTICS"  # LOW - Analytics use: aggregation only, no details exposed
    SHARING = "SHARING"      # FULL - External sharing: full masking


class ContextAwareMaskingService:
    """Context-aware desensitization service - Automatically selects appropriate level based on scenario"""
    
    def __init__(self, default_level: DesensitizationLevel = DesensitizationLevel.SHARING):
        self.default_level = default_level
        self.context_rules = {
            # Rule: Which scenarios trigger which levels
            'system_log': DesensitizationLevel.LOGGING,
            'debug_trace': DesensitizationLevel.DEBUGGING,
            'analytics_report': DesensitizationLevel.ANALYTICS,
            'api_response': DesensitizationLevel.SHARING,
            'user_display': DesensitizationLevel.SHARING,
            'internal_diagnostic': DesensitizationLevel.DEBUGGING
        }
        
    def get_masking_level_for_context(self, context_type: str) -> DesensitizationLevel:
        """Get masking level based on context type"""
        return self.context_rules.get(context_type, self.default_level)
    
    def mask_with_level(self, text: str, level: DesensitizationLevel, 
                       pattern_matcher=None) -> str:
        """
        Execute masking at specified level
        
        Args:
            text: Original text
            level: Masking level
            pattern_matcher: Custom pattern matcher
            
        Returns:
            Masked text
        """
        if not text or len(text) < 5:
            return text
        
        # Apply different masking strategies based on level
        if level == DesensitizationLevel.LOGGING:
            # HIGH - Full masking, no traces left
            return self._full_mask_logging(text)
        
        elif level == DesensitizationLevel.DEBUGGING:
            # MEDIUM - Keep first 4 and last 4 characters for debugging
            return self._partial_mask_debugging(text)
        
        elif level == DesensitizationLevel.ANALYTICS:
            # LOW - Only aggregate statistics, don't return original values
            return "[AGGREGATED]"
        
        elif level == DesensitizationLevel.SHARING:
            # FULL - Full masking for external display
            return self._full_mask_sharing(text)
        
        return text
    
    def _full_mask_logging(self, text: str) -> str:
        """Logging level: Full coverage"""
        if len(text) <= 8:
            return "[REDACTED]"
        return "*" * min(16, len(text)) + "..."
    
    def _partial_mask_debugging(self, text: str) -> str:
        """Debugging level: Keep beginning and end for troubleshooting"""
        if len(text) <= 8:
            return "[REDACTED]"
        first_part = text[:4]
        last_part = text[-4:]
        middle_length = max(3, len(text) - 8)
        return f"{first_part}{'*' * middle_length}{last_part}"
    
    def _full_mask_sharing(self, text: str) -> str:
        """Sharing level: Full coverage for external display"""
        if len(text) <= 8:
            return "[REDACTED]"
        return "*" * min(16, len(text)) + "..."
    
    def mask_context_aware(self, context_data: Dict[str, Any], 
                          scene_type: str) -> Dict[str, Any]:
        """
        Intelligently mask entire context based on scene type
        
        Args:
            context_data: Context dictionary
            scene_type: Usage scenario (system_log/debug_trace/analytics_report/api_response etc.)
            
        Returns:
            Masked dictionary
        """
        level = self.get_masking_level_for_context(scene_type)
        
        masked = {}
        for key, value in context_data.items():
            if isinstance(value, str):
                # 对敏感字段使用更高强度
                is_sensitive_field = any(sens in key.lower() 
                                        for sens in ['password', 'token', 'secret', 'api_key'])
                
                intensity_multiplier = 2 if is_sensitive_field else 1
                
                masked[key] = self._apply_intelligent_mask(
                    value, level, sensitivity=intensity_multiplier
                )
            elif isinstance(value, dict):
                # 递归处理嵌套字典
                masked[key] = self.mask_context_aware(value, scene_type)
            elif isinstance(value, list):
                masked[key] = [self._mask_list_item(item, scene_type) 
                              for item in value]
            else:
                masked[key] = value
        
        return masked
    
    def _apply_intelligent_mask(self, text: str, level: DesensitizationLevel, 
                               sensitivity: int = 1) -> str:
        """Intelligently select masking intensity based on sensitivity and level"""
        
        # The higher the sensitivity, the more thorough the masking
        if sensitivity >= 2:
            return "[***HIDDEN**]"
        
        base_mask = self.mask_with_level(text, level)
        
        # Further process highly sensitive content
        if sensitivity == 1 and len(text) > 10:
            return f"[MASKED:{len(text)}]"
        
        return base_mask
    
    def _mask_list_item(self, item, scene_type: str):
        """Recursively process list items"""
        if isinstance(item, dict):
            return self.mask_context_aware(item, scene_type)
        elif isinstance(item, str):
            level = self.get_masking_level_for_context(scene_type)
            return self.mask_with_level(item, level)
        return item
    
    def should_use_aggregation(self, query_type: str) -> bool:
        """Determine whether aggregation query should be used instead of exact match"""
        aggregation_triggers = [
            'analytics', 'report', 'summary', 'overview'
        ]
        return any(trigger in query_type.lower() 
                  for trigger in aggregation_triggers)


# Usage example
if __name__ == '__main__':
    service = ContextAwareMaskingService()
    
    # Simulate masking behavior in different scenarios
    sample_data = {
        'user_email': 'test@example.com',
        'api_token': 'sk-abc123def456ghi789jkl012mno345pqr678stu901vwx234yz',
        'session_id': 'sess_1234567890abcdef',
        'debug_info': {
            'request_headers': {'Authorization': 'Bearer token-value'},
            'user_ip': '192.168.1.100'
        }
    }
    
    print("=== 场景1: API响应 (SHARING) ===")
    result = service.mask_context_aware(sample_data, 'api_response')
    for k, v in result.items():
        if isinstance(v, dict):
            print(f"  {k}: {{...}}")
        else:
            print(f"  {k}: {v}")
    
    print("\n=== 场景2: 调试日志 (DEBUGGING) ===")
    result = service.mask_context_aware(sample_data, 'debug_trace')
    for k, v in result.items():
        if isinstance(v, dict):
            print(f"  {k}: {{...}}")
        else:
            print(f"  {k}: {v}")
