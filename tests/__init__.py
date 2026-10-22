"""测试包。

设为包（``tests/__init__.py``）的原因：``tests/fakes/fake_parser.py`` 需要被多个用例
以稳定路径导入（``from tests.fakes.fake_parser import FakeParser``），而 pytest 默认的
``prepend`` 导入模式只会把"测试模块所在目录"塞进 ``sys.path``，非测试模块拿不到。
"""
