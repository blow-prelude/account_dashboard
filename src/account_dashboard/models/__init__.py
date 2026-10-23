"""对外 DTO 集合（Pydantic 为单一事实源，SDD §6.3）。

``staging`` 与 ``ingest`` 互相引用（``BatchDetailDTO.report`` 要
``IngestReportDTO``，``TraceDTO.batch`` 要 ``BatchDTO``），模块级双向 import
在 Python 里无解。解法：``staging`` 只用 TYPE_CHECKING + 字符串前向引用，
本文件在**包初始化时**按「先 staging 后 ingest」装载两个子模块，并在此补齐
``BatchDetailDTO`` 的前向引用。因为 Python 保证任何
``account_dashboard.models.*`` 的 import 都先执行本文件，所以与调用方的
import 顺序无关。

改动这两个模块的相互引用前，先读 ``tests/unit/test_dto_wiring.py``。
"""

from account_dashboard.models import ingest as _ingest
from account_dashboard.models.staging import BatchDetailDTO

# 唯一允许使用 _types_namespace 的地方：前向引用解析需要显式命名空间
BatchDetailDTO.model_rebuild(
    force=True,
    _types_namespace={"IngestReportDTO": _ingest.IngestReportDTO},
)
