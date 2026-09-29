# SPEC-030：管理端登录HTTP基础

状态：Verified（管理HTTP认证与PG会话；网页和部署待完成）。用户已确认管理端HTTP、浏览器、聊天联动测试边界，内部实现自主决定。本切片验收HTTP登录基础，网页、启动命令及配置发布随后接入，不称为完整管理端交付。

FastAPI处理HTTP，pwdlib Argon2验证单管理员密码；管理配置仅传入哈希，聊天运行时不加载管理凭据。数据库使用现有PG新增admin schema，与app业务表区分，实际部署还需配置独立数据库角色权限。

POST /admin/api/login接收JSON password；合法Origin必须与配置管理origin完全一致。成功建立随机256bit不透明session，PG仅保存session摘要、独立CSRF令牌、截止时间及凭据版本摘要，Cookie为HttpOnly、SameSite=Strict、Path=/admin，HTTPS要求Secure。HTTP仅允许本机origin。GET /admin/api/session返回已认证状态与CSRF；POST /admin/api/logout须Origin与X-CSRF-Token，服务端撤销session后删除Cookie。

会话固定8小时初值，可配置短期限用于部署/验收；无滑动续期。换密码哈希使旧会话无效。服务重建后会话继续有效，退出后旧Cookie不可重放。浏览器存储不保存密码或session，页面JS仅持有CSRF。所有认证响应no-store，校验失败不能回显原密码。

登录限速用PG共享计数，单管理员全局固定窗口每60秒最多5次尝试（包含成功），在密码计算之前预留名额；首版统一固定参数，避免各实例配置不同绕过规则，不宣称任意滚动60秒最多5次。该规则适合默认本机单管理员入口，不把IP头作为可信身份。密码计算放在线程池，进程内并发上限2，防止阻塞事件循环和过量Argon2内存。

- AC1：未登录401；正确密码设置受限Cookie并可查看会话，服务重建后有效。
- AC2：错误密码401；非法请求422但不反射密码；Origin缺失/不符403，不能登录。
- AC3：无/错误CSRF退出403；正确退出清除服务端会话，重放Cookie401。
- AC4：到期和凭据变更后401。
- AC5：并发/重建服务不能绕过共享限速，超限429且不发Cookie。

非目标：注册、多管理员、公开互联网部署、OAuth、完整配置发布、前端页面。数据库不可用须失败关闭，不回退成内存认证。日志不得记录密码、哈希、Cookie、CSRF或其前缀。
