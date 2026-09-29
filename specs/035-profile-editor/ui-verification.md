# UI验证

Surface：登录后的机器人资料编辑表单。Primary workflow：读取→修改→保存草稿→发布。

## Ran

- webapp-ui-skill的布局、状态、隐私和视觉验证规则已读取；本地优先，没有向外部设计服务传图。
- 真实Chromium接独立管理服务与PG，1280×800、390×844完成保存/刷新/发布。
- 状态覆盖：loading读取中；empty无草稿/发布；error读取断网、写响应丢失、409、422、401、403；disabled未保存/提交/未知结果；success草稿保存和发布；focus截图可见输入焦点。
- 状态扫描：node /home/nonokoovo/.codex/skills/webapp-ui-skill/scripts/check_state_coverage.ts --root dashboard/src --out artifacts/profile-state-coverage.json。唯一缺失标记selected，本页无列表/选项卡选中状态，判定不适用；静态正则不作为行为通过证据。
- 浏览器断言没有横向溢出或pageerror；截图artifacts/profile-editor-1280.png、profile-editor-390.png使用合成数据，未提交仓库。

## Manual

两个尺寸截图已打开检查。标签、输入框、说明和按钮无重叠；手机按钮同行且可读。发布后再次编辑会清除过时成功提示，保留未保存说明。表单为单列；暂不添加无实际功能的导航。

## Skipped

未单独运行skill自带visual_smoke_test.mjs：它只取HTML且没有浏览器驱动；本轮真实页面URL由隔离测试夹具临时启动和关闭，采用实际Playwright加载/交互/截图验证。未运行云端视觉服务或外部截图上传。

## Planned

历史版本/回滚与差异对照，运行实例实际采用展示。真实VPS、HTTPS反向代理和生产数据库角色隔离仍需部署验收。
