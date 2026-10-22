"""解析内核公共子包（C2-A）。

B 线（缓冲区与向导）只允许使用 ``base`` / ``registry`` / ``errors`` 三个模块，
**不得** import 具体适配器（``wechat_xlsx`` 等），否则 C3 加新渠道时 B 线要跟着改。
"""
