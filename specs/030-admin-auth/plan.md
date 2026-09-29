# 实施

按HTTP边界逐行为红绿：登录与会话持久化 → 退出/CSRF → Origin与错误输入 → 期限与凭据变更 → 跨实例登录限速。真实隔离PG，ASGI HTTP客户端，不检查内部表行或mock自有存储。新增0010迁移。密码算法和Cookie编码交给库，不自写密码算法或签名协议。

参考FastAPI密码哈希教程：https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/
pwdlib：https://frankie567.github.io/pwdlib/guide/
Starlette Cookie：https://starlette.dev/responses/

本应用选择服务端opaque session是为满足即时撤销；没有照搬教程JWT。Cookie安全参数使用Starlette既有接口。前端和CLI另行接线后才可宣称管理员能从浏览器实际使用。
