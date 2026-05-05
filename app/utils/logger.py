import logging
import os
from datetime import datetime
from typing import Optional
from logging.handlers import RotatingFileHandler
from logging import Formatter


# ANSI 颜色代码
class ColorFormatter(Formatter):
    """彩色日志Formatter"""
    
    COLORS = {
        'DEBUG': '\033[36m',    # 青色
        'INFO': '\033[32m',     # 绿色
        'WARNING': '\033[33m',  # 黄色
        'ERROR': '\033[31m',   # 红色
        'CRITICAL': '\033[35m', # 紫色
    }
    RESET = '\033[0m'
    
    def format(self, record):
        # 获取颜色
        color = self.COLORS.get(record.levelname, '')
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


# 日志级别配置
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# 日志目录
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)


class Logger:
    """统一日志管理器"""
    
    _loggers = {}
    
    @classmethod
    def get_logger(cls, name: str = "app") -> logging.Logger:
        """获取带文件输出的日志器"""
        if name in cls._loggers:
            return cls._loggers[name]
        
        logger = logging.getLogger(name)
        logger.setLevel(getattr(logging, LOG_LEVEL))
        logger.propagate = False
        
        # 避免重复添加 handler
        if not logger.handlers:
            # 控制台输出（彩色）
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_format = ColorFormatter(
                "%(asctime)s [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            console_handler.setFormatter(console_format)
            logger.addHandler(console_handler)
            
            # 文件输出（普通格式）
            log_file = os.path.join(LOG_DIR, f"{name}.log")
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=10 * 1024 * 1024,  # 10MB
                backupCount=5,
                encoding="utf-8"
            )
            file_handler.setLevel(logging.DEBUG)
            file_format = Formatter(
                "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            file_handler.setFormatter(file_format)
            logger.addHandler(file_handler)
        
        cls._loggers[name] = logger
        return logger


def get_logger(name: str = "app") -> logging.Logger:
    """快捷获取日志器"""
    return Logger.get_logger(name)


# 各模块日志器快捷获取
app_logger = Logger.get_logger("app")
api_logger = Logger.get_logger("api")
agent_logger = Logger.get_logger("agent")
core_logger = Logger.get_logger("core")
rag_logger = Logger.get_logger("rag")
memory_logger = Logger.get_logger("memory")


# 便捷函数（兼容旧代码）
def info(tag: str, message: str):
    """info 日志"""
    app_logger.info(f"[{tag}] {message}")


def debug(tag: str, message: str):
    """debug 日志"""
    app_logger.debug(f"[{tag}] {message}")


def warning(tag: str, message: str):
    """warning 日志"""
    app_logger.warning(f"[{tag}] {message}")


def error(tag: str, message: str):
    """error 日志"""
    app_logger.error(f"[{tag}] {message}")


# 兼容旧的 print 风格日志
def log(tag: str, message: str, level: str = "INFO"):
    """通用日志，兼容 print"""
    level = level.upper()
    if level == "DEBUG":
        debug(tag, message)
    elif level == "WARNING":
        warning(tag, message)
    elif level == "ERROR":
        error(tag, message)
    else:
        info(tag, message)