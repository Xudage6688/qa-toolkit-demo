"""pytest 共享配置：将项目根目录加入 sys.path，各测试文件无需重复注入。"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
