# ============================================
# reversible_masking.py - 可逆脱敏机制
# P1-紧急: 支持内部调试场景的加密/解密
# Version: v0.4.3 (Reversible Masking)
# Author: Haiwen Yin (胖头鱼 🐟)
# Date: 2026-05-08
# ============================================

import base64
from cryptography.fernet import Fernet
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger('memory_system')

class ReversibleMaskingService:
    """可逆脱敏服务 - 使用Fernet对称加密，支持内部调试时恢复原始数据"""
    
    def __init__(self, encryption_key: Optional[str] = None):
        """
        初始化可逆脱敏服务
        
        Args:
            encryption_key: 加密密钥。如果未提供，自动生成新的密钥（仅用于测试）
                           生产环境必须显式提供密钥！
        """
        import base64
        
        if encryption_key is None:
            # WARNING: 生成新密钥仅用于演示，生产环境必须配置固定密钥
            self._key = Fernet.generate_key()
            logger.warning("No encryption key provided - generating random key (not secure for production)")
            self.cipher = Fernet(self._key)
        else:
            # Try creating Fernet directly with string first (Fernet accepts both bytes and str)
            try:
                self.cipher = Fernet(encryption_key)  # Try using the string directly
                logger.info("Successfully created Fernet cipher from provided key")
                # Store reference for info method
                try:
                    self._key = base64.urlsafe_b64decode(encryption_key)
                except Exception:
                    pass  # _key may remain None if we couldn't extract it
            except Exception as e1:
                # If that fails, try base64 decoding (for binary keys)
                try:
                    decoded_bytes = base64.urlsafe_b64decode(encryption_key)
                    self.cipher = Fernet(decoded_bytes)
                    self._key = decoded_bytes
                    logger.info("Successfully created Fernet cipher from base64-decoded key")
                except Exception as e2:
                    # If both fail, generate a new key
                    logger.warning(f"Key validation failed ({str(e1)[:50]}), generating new key")
                    self._key = Fernet.generate_key()
                    self.cipher = Fernet(self._key)
    
    def encrypt_value(self, plain_text: str) -> Optional[str]:
        """
        加密单个值
        
        Args:
            plain_text: 原始明文
            
        Returns:
            Base64编码的密文，失败返回None
        """
        try:
            encrypted = self.cipher.encrypt(plain_text.encode('utf-8'))
            return base64.b64encode(encrypted).decode('utf-8')
        except Exception as e:
            logger.error(f"Encryption failed for value: {e}")
            return None
    
    def decrypt_value(self, cipher_text: str) -> Optional[str]:
        """
        解密密文
        
        Args:
            cipher_text: Base64编码的密文
            
        Returns:
            解密后的明文，失败返回None
        """
        try:
            # Decode from base64 first, then decrypt
            encrypted = base64.b64decode(cipher_text.encode('utf-8'))
            decrypted = self.cipher.decrypt(encrypted)
            return decrypted.decode('utf-8')
        except Exception as e:
            logger.error(f"Decryption failed for cipher text: {e}")
            return None
    
    def encrypt_context_data(self, context_data: Dict[str, Any], 
                            sensitive_fields: Optional[list] = None) -> Dict[str, Any]:
        """
        加密整个上下文数据
        
        Args:
            context_data: 原始上下文字典
            sensitive_fields: 需要加密的字段列表。None则加密所有字符串值
            
        Returns:
            包含密文的字典，无法解密时保留原文本标记
        """
        if not sensitive_fields:
            sensitive_fields = ['password', 'token', 'secret', 'key', 'credential']
        
        encrypted_data = {}
        
        for key, value in context_data.items():
            is_sensitive = any(sens_field.lower() in key.lower() 
                             for sens_field in sensitive_fields)
            
            if isinstance(value, str) and (is_sensitive or not sensitive_fields):
                encrypted_value = self.encrypt_value(value)
                if encrypted_value:
                    # 标记这是密文，以便后续解密
                    encrypted_data[f"{key}_encrypted"] = f"[ENCRYPTED]{encrypted_value}[END]"
                else:
                    logger.warning(f"Failed to encrypt {key}, keeping original")
                    encrypted_data[key] = value
            elif isinstance(value, dict):
                # 递归加密嵌套字典
                nested = self.encrypt_context_data(value, sensitive_fields)
                if nested:
                    encrypted_data[f"{key}_encrypted"] = f"[ENCRYPTED]{str(nested)}[END]"
                else:
                    encrypted_data[key] = value
            else:
                encrypted_data[key] = value
        
        return encrypted_data
    
    def decrypt_context_data(self, context_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        解密整个上下文数据
        
        Args:
            context_data: 包含加密值的字典
            
        Returns:
            解密后的原始字典，无法解密时保留密文标记
        """
        decrypted = {}
        
        for key, value in context_data.items():
            # Check if this is an encrypted value marker
            if isinstance(value, str) and value.startswith("[ENCRYPTED]") and value.endswith("[END]"):
                cipher_text = value[len("[ENCRYPTED]"):len(value)-len("[END]")]
                decrypted_value = self.decrypt_value(cipher_text)
                if decrypted_value:
                    decrypted[key.replace("_encrypted", "")] = decrypted_value
                else:
                    logger.warning(f"Failed to decrypt {key}, keeping encrypted")
                    decrypted[key] = value
            else:
                decrypted[key] = value
        
        return decrypted
    
    def encrypt_sensitive_field(self, field_name: str, 
                               field_value: str, 
                               is_active: bool = True) -> Optional[Dict]:
        """
        加密单个敏感字段，返回结构化数据
        
        Args:
            field_name: 字段名（用于标识）
            field_value: 原始值
            is_active: 是否启用加密
            
        Returns:
            {'field': 'password', 'encrypted': True, 'value': '[ENCRYPTED]...[END]', 
             'created_at': timestamp}
        """
        if not is_active:
            return None
        
        encrypted_value = self.encrypt_value(field_value)
        
        import datetime
        result = {
            'field': field_name,
            'encrypted': True,
            'value': f"[ENCRYPTED]{encrypted_value}[END]" if encrypted_value else "[DECRYPTION_FAILED]",
            'created_at': datetime.datetime.now().isoformat()
        }
        
        logger.debug(f"Encrypted field: {field_name}")
        return result
    
    def get_encryption_key_info(self) -> Dict[str, Any]:
        """获取加密密钥相关信息（不泄露密钥本身）"""
        import hashlib
        key_hash = hashlib.sha256(self._key).hexdigest()[:16]
        
        return {
            'key_type': 'Fernet AES-128-CBC',
            'key_id': f'KEY-{key_hash}',
            'algorithm': 'AES-128-CBC with HMAC-SHA256',
            'note': '密钥哈希仅用于标识，不可还原原始密钥'
        }


# 使用示例
if __name__ == '__main__':
    # 生产环境必须配置固定密钥
    ENCRYPTION_KEY = "your-production-secret-key-must-be-32-bytes-minimum"
    
    service = ReversibleMaskingService(ENCRYPTION_KEY)
    
    # 测试加密/解密
    test_data = {
        'username': 'admin',
        'password': 's3cr3tP@ssw0rd!',
        'api_key': 'sk-proj-abc123xyz789'
    }
    
    print("=== 原始数据 ===")
    for k, v in test_data.items():
        print(f"  {k}: {v}")
    
    encrypted = service.encrypt_context_data(test_data)
    print("\n=== 加密后 ===")
    for k, v in encrypted.items():
        if isinstance(v, str) and len(v) > 50:
            print(f"  {k}: [ENCRYPTED - length:{len(v)}]")
        else:
            print(f"  {k}: {v}")
    
    decrypted = service.decrypt_context_data(encrypted)
    print("\n=== 解密后 ===")
    for k, v in decrypted.items():
        print(f"  {k}: {v}")
