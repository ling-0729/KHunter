#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
加密工具类 - 提供对称加密解密功能
"""

import base64
from cryptography.fernet import Fernet

class CryptoUtils:
    """加密工具类"""
    
    # 默认密钥（需要在实际使用时替换为安全的密钥）
    DEFAULT_KEY = b'your-secret-key-here-must-be-32-url-safe-base64-bytes'
    
    @staticmethod
    def generate_key() -> bytes:
        """生成加密密钥
        
        Returns:
            32字节的URL安全base64编码密钥
        """
        return Fernet.generate_key()
    
    @staticmethod
    def encrypt(data: str, key: bytes = None) -> str:
        """加密字符串
        
        Args:
            data: 要加密的字符串
            key: 加密密钥，默认为DEFAULT_KEY
            
        Returns:
            加密后的base64字符串
        """
        if key is None:
            key = CryptoUtils.DEFAULT_KEY
        
        # 确保密钥是URL安全的base64编码
        try:
            fernet = Fernet(key)
        except ValueError:
            # 如果密钥无效，使用默认密钥重新生成
            fernet = Fernet(CryptoUtils.generate_key())
        
        encrypted = fernet.encrypt(data.encode('utf-8'))
        return base64.urlsafe_b64encode(encrypted).decode('utf-8')
    
    @staticmethod
    def decrypt(encrypted_data: str, key: bytes = None) -> str:
        """解密字符串
        
        Args:
            encrypted_data: 加密的base64字符串
            key: 解密密钥，默认为DEFAULT_KEY
            
        Returns:
            解密后的原始字符串
        """
        if key is None:
            key = CryptoUtils.DEFAULT_KEY
        
        try:
            fernet = Fernet(key)
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_data)
            decrypted = fernet.decrypt(encrypted_bytes)
            return decrypted.decode('utf-8')
        except Exception as e:
            # 如果解密失败，返回原始数据
            return encrypted_data

# 测试
if __name__ == '__main__':
    # 生成密钥
    key = CryptoUtils.generate_key()
    print("生成的密钥:", key.decode('utf-8'))
    
    # 测试加密解密
    original = "test_file.json"
    encrypted = CryptoUtils.encrypt(original, key)
    decrypted = CryptoUtils.decrypt(encrypted, key)
    
    print(f"原始数据: {original}")
    print(f"加密后: {encrypted}")
    print(f"解密后: {decrypted}")
    print(f"解密成功: {original == decrypted}")
