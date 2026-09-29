# SPEC-031：独立管理服务启动与密码初始化

状态：Verified（Linux本地子进程、HTTP登录及启动门禁；浏览器页面与真实部署待完成）。沿用已确认的配置/日志、HTTP入口测试边界。通过真实子进程启动和HTTP登录观察行为，不mock服务器。

提供`python -m xiaolv.admin_server serve`及`init-password --output PATH`。初始化默认使用终端隐藏输入、二次确认；自动化显式`--password-stdin`从标准输入读取，密码不能作为命令行参数或环境变量传入。密码长度12–1024，写入Argon2哈希文件，权限0600，新建且拒绝覆盖。stdout/stderr不输出密码或哈希。

管理启动只读取XIAOLV_ADMIN_DATABASE_URL、XIAOLV_ADMIN_PASSWORD_HASH_FILE、XIAOLV_ADMIN_PORT及XIAOLV_ADMIN_ORIGIN。默认127.0.0.1:8081、本机HTTP；外部HTTPS origin供本机反向代理场景预留，服务器始终绑定127.0.0.1。无需QQ或模型凭据，不启动聊天进程。数据库URL必须postgresql+psycopg，文件限制大小、权限、常规文件且非符号链接，错误返回退出码2且不打印敏感值。

启动先验证密码哈希和数据库迁移版本等于当前head；不自动修改数据库。Uvicorn负责HTTP和信号处理，关闭时释放DB资源。使用现有日志格式；关闭访问日志和代理头信任，不把请求路径、认证数据或异常正文打印到日志。管理服务异常输出分类错误，运行故障退出码1。

- AC1：初始化文件后子进程启动HTTP，凭该密码登录成功，SIGTERM正常退出；日志无秘密。
- AC2：缺配置、不安全权限/坏哈希、非法端口或非PG DSN在监听前失败，错误不回显值。
- AC3：schema旧版本或数据库不可用不启动HTTP；不自动迁移。
- AC4：初始化拒绝覆盖文件和不合法密码。

本切片不含浏览器页面、配置发布和聊天联动；不能仅有HTTP登录就宣称管理网页已完成。角色隔离与HTTPS真实部署另验收。
