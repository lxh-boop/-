该压缩包用于判断：
1. 三份问答日志是否生成于 Memory V2 重构之前；
2. 当前实际运行入口是否仍引用旧 build_agent_context/compressor 链路；
3. Memory V2 是否只新增了文件但没有接入 Executor；
4. 后续覆盖是否重新带回旧 executor.py；
5. Streamlit/Python 进程是否仍加载旧模块；
6. 金额和小数误识别为股票代码的旧正则链路是否仍在生产路径。

注意：
- 脚本只复制文件，不修改项目。
- local_config.py/config.py 的副本会尝试脱敏。
- 上传前仍建议人工检查压缩包中是否存在密钥、Token、密码或隐私数据。
