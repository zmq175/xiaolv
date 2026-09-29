# 独立管理服务

当前提供密码初始化、认证HTTP及浏览器登录/会话/退出页面；配置发布与运行概览仍待实现。Linux/Python 3.12，管理进程不会启动QQ连接或模型调用。前端用Node 24构建，部署运行时只需Python服务。

## 初始化与启动

先按[数据库说明](postgres-development.md)以迁移角色显式执行迁移至head。管理服务只检查版本，不自动建表。建议为管理服务单独配置数据库角色：可读公共alembic_version，可使用admin schema并操作其会话/限速表；聊天角色不授予admin schema访问。当前尚无角色自动创建脚本，必须由部署配置落实。

```sh
uv sync --locked
npm ci --prefix dashboard
npm run build --prefix dashboard
mkdir -p runtime
PYTHONPATH=src uv run python -m xiaolv.admin_server init-password --output runtime/admin.hash
```

命令在终端隐藏输入并确认密码（12–1024字），以0600权限新建哈希文件，拒绝覆盖已有文件。不要把密码或哈希放进仓库。自动化可明确使用`--password-stdin`从秘密管理工具的管道输入一行密码；默认无终端直接拒绝，不让getpass静默退化成回显输入。不要把实际密码写在命令参数、shell历史或脚本正文中。

设置以下变量；数据库URL示例不含密码，连接凭据由部署环境提供。运行时不会自动读取.env文件。

```sh
export XIAOLV_ADMIN_DATABASE_URL='postgresql+psycopg://xiaolv_admin@127.0.0.1/xiaolv'
export XIAOLV_ADMIN_PASSWORD_HASH_FILE="$PWD/runtime/admin.hash"
export XIAOLV_ADMIN_PORT=8081
export XIAOLV_ADMIN_ORIGIN='http://127.0.0.1:8081'
PYTHONPATH=src uv run python -m xiaolv.admin_server serve
```

固定绑定127.0.0.1。远程VPS通过SSH本地转发访问；默认用相同端口，例如`ssh -L 8081:127.0.0.1:8081 your-vps`，浏览器地址为http://127.0.0.1:8081。若转发端口不同，Origin必须设为浏览器实际使用的origin。通过本机反向代理提供HTTPS时配置相应https origin；服务不信任转发头，不能用请求头更改认证来源。

访问`/admin/`进入登录页面。页面与认证API同源，登录后显示真实会话状态，可退出；尚无配置发布和仪表盘，不展示模拟运行数据。未构建前端时页面返回503并提示构建，不影响API。

HTTP接口：POST `/admin/api/login`（JSON password且Origin匹配）、GET `/admin/api/session`、POST `/admin/api/logout`（Origin与X-CSRF-Token）。未登录session返回401；应用启动日志只表示启动过程开始，可通过HTTP响应确认实际已监听。

## 退出与凭据更换

SIGTERM会让Uvicorn停止请求并完成数据库资源释放。stdout不输出秘密，日志复用项目格式；关闭HTTP访问日志以避免记录认证相关URL，Uvicorn异常正文也不原样输出。

配置错误退出2，数据库启动故障或schema不匹配退出1。权限必须是仅当前用户可读写的普通文件，不接受符号链接。通过进程环境传管理专用DSN，不从聊天DSN或QQ身份推导管理员权限。

更换密码时停止所有管理实例，使用init-password生成新的文件，再原子替换原哈希文件并重启全部实例。旧会话绑定旧哈希版本，将无法继续使用；不要让仍使用旧文件的实例留在运行中。init-password刻意不提供静默覆盖，以免误覆盖路径。

本地Chromium已验证登录页面在1280×800与390×844下的登录、刷新和退出，以及网络错误/提交中/限速状态。尚未验收VPS部署、HTTPS代理和数据库角色隔离。当前日志生命周期未接独立OTel管理请求span，认证审计和过期会话清理仍待补充。
