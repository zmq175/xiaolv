# 独立管理服务

当前提供密码初始化、认证HTTP及浏览器登录/会话/退出页面，以及人设草稿、发布和回滚HTTP接口。网页已支持人设编辑、草稿保存与发布；网页也提供发布差异、版本历史与回滚；运行概览仍待实现。在线聊天每回合读取已发布人设。Linux/Python 3.12，管理进程不会启动QQ连接或模型调用。前端用Node 24构建，部署运行时只需Python服务。

## 初始化与启动

先按[数据库说明](postgres-development.md)以迁移角色显式执行迁移至head。管理服务只检查版本，不自动建表。建议为管理服务单独配置数据库角色：可读公共alembic_version，可使用admin schema并操作会话、限速和配置管理表，以及app schema中的人设发布表和序列；聊天角色不授予admin schema访问。当前尚无角色自动创建脚本，必须由部署配置落实。

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

访问`/admin/`进入登录页面。页面与认证API同源，登录后显示会话状态，可编辑机器人名称、别名、人设、参与风格和回复风格。先保存草稿再发布；未保存修改时发布按钮禁用。没有仪表盘或模拟运行数据。未构建前端时页面返回503并提示构建，不影响API。

HTTP接口：POST `/admin/api/login`（JSON password且Origin匹配）、GET `/admin/api/session`、POST `/admin/api/logout`（Origin与X-CSRF-Token）。未登录session返回401；应用启动日志只表示启动过程开始，可通过HTTP响应确认实际已监听。

## 退出与凭据更换

SIGTERM会让Uvicorn停止请求并完成数据库资源释放。stdout不输出秘密，日志复用项目格式；关闭HTTP访问日志以避免记录认证相关URL，Uvicorn异常正文也不原样输出。

配置错误退出2，数据库启动故障或schema不匹配退出1。权限必须是仅当前用户可读写的普通文件，不接受符号链接。通过进程环境传管理专用DSN，不从聊天DSN或QQ身份推导管理员权限。

更换密码时停止所有管理实例，使用init-password生成新的文件，再原子替换原哈希文件并重启全部实例。旧会话绑定旧哈希版本，将无法继续使用；不要让仍使用旧文件的实例留在运行中。init-password刻意不提供静默覆盖，以免误覆盖路径。

本地Chromium已验证登录页面在1280×800与390×844下的登录、刷新和退出，以及网络错误/提交中/限速状态。尚未验收VPS部署、HTTPS代理和数据库角色隔离。当前日志生命周期未接独立OTel管理请求span，认证审计和过期会话清理仍待补充。

## 人设配置HTTP接口

- GET `/admin/api/profile`读取管理版本、草稿及已发布快照；首次草稿和发布均为null。
- PUT `/admin/api/profile/draft`提交`expected_version`和`profile`，只保存草稿。
- POST `/admin/api/profile/publish`提交`expected_version`，将草稿创建为新的发布版本。
- POST `/admin/api/profile/rollback`提交`expected_version`和`release_version`，复制旧快照为新发布，保留当前草稿。
- GET `/admin/api/profile/releases/{version}`读取指定快照。

上述接口均要求登录；写入还要求Origin、X-CSRF-Token与Idempotency-Key（1–128位字母、数字、下划线或连字符）。管理version用于并发控制，陈旧写入返回409。相同幂等键重试相同请求返回原操作结果；键复用于不同请求返回409。重试结果可能早于当前状态，需重新GET核对最新状态。字段校验422只返回位置和错误类型。

“已发布”表示控制面事务已提交。在线聊天在下一回合参与判断前读取当前发布，整回合固定使用同一版本；无发布时使用启动配置，已有草稿不参与聊天。读取失败结束为profile_error，超时结束为expired，不静默使用旧配置。发布历史由接口保持不变，不声称能够防止具有数据库写权限的操作员直接修改记录。日志profile_selected记录实际回合、来源及所选版本（startup时版本为none），不含人设正文。该日志表示回合已选择版本，不等于已回复；管理页面的实例心跳和采用版本展示、数据库角色授权仍待实现。

## 浏览器编辑与发布

初次没有草稿时显示空表单，别名每行一个。保存只修改草稿，页面刷新后仍可继续编辑；发布成功展示版本号，后续聊天回合读取该版本。网页不宣称全部运行实例已采用。

发生并发冲突时保留本地内容，点击“放弃本地修改并加载最新资料”才读取新草稿。请求结果未知时暂时锁定表单，点击“重试原操作”使用同一个幂等键恢复；成功后重新读取最新状态。资料和重试状态仅保存在内存，不在浏览器持久存储，刷新页面会丢失本地未保存内容。字段错误可修改后重新保存；会话失效返回登录页。

网页“发布差异”展示已保存草稿与当前发布的逐字段变化，不包含未保存编辑。“查看历史版本”按需读取，支持加载更早记录；选择版本后先查看回滚差异，再点击回滚。回滚创建新发布且保留草稿；存在未保存修改时禁止回滚。列表失败可重新读取，版本预览失败可点击同一版本重试。

历史API：GET `/admin/api/profile/releases`，参数limit为1–50（默认20），before为正bigint范围版本上界且不包含该版本；返回items和next_before。列表仅含version、name、created_at，不传人设正文；正文按单个版本读取。

## 会话停用控制

聊天服务启动时登记配置允许的群/私聊，登记不覆盖已有停用状态。当前管理HTTP提供GET /admin/api/conversations（limit默认20，最多50，after游标）以及PUT /admin/api/conversations/{conversation_id}。写入JSON为enabled布尔值和expected_version，并要求登录Cookie、Origin、X-CSRF-Token、Idempotency-Key。同会话同键同请求返回原响应，同键变参或旧版本返回409。未知会话404。列表表示已登记会话，不是实时连接清单。

停用与旧回合epoch失效同事务；恢复不会让旧回复重新有效。在线模型每个阶段以及PG最终发送认领读取当前权限。环境路由仍限制可执行范围，管理恢复不能打开未配置路由。已被最终发送认领接受的在途请求可能完成，不能据此承诺撤销平台副作用。管理台会话列表可停用/恢复、刷新和加载更多；响应丢失使用原幂等请求重试，版本冲突要求刷新当前状态。停用和恢复会清除尚未认领的排队候选。升级前按现有流程执行Alembic迁移0012；旧schema由启动门禁拒绝。
