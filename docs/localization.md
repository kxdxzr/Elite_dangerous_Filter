# Language support / 语言扩展

目前仅启用中文（`zh`）与英文（`en`）。本次整理没有新增语言，也不改变条件文件、会话里的条件值、游戏名称或API字段。

## 统一入口

- `src/i18n.py`：`LANGUAGES` 是唯一启用语言列表，映射语言代码与其本族语显示名称。下拉列表、语言校验、会话恢复及EXE冒烟报告均使用它。
- `src/translations/en.py`：现有英文 `CATALOG`、兼容旧动态消息的 `FRAGMENTS`、结构化 `MESSAGES`。
- `src/translations/zh.py`：结构化中文 `MESSAGES`；普通中文界面文本作为稳定源文保留。
- `translate(text, language)`／`Localizer.tr(text)`：翻译完整静态源文。中文源文留在控件调用处不是中英文分支；译文集中在语言包。
- `message(key, language, **values)`／`Localizer.message(key, **values)`：按稳定消息ID翻译完整模板，再填入变量。CSV列名、进度、动态概要等使用这一入口，不在业务代码里写 `language == 'en'`。
- `export_text`：集中处理语言包的导出策略；目前保留旧英文CSV对残留汉字的转义行为，不改变既有导出约定。

## 将来添加语言

1. 新建 `src/translations/<code>.py`，提供 `CATALOG` 和 `MESSAGES` 字典。`CATALOG` 以中文源文为键，`MESSAGES` 以稳定ID为键；不要翻译游戏名称、API键或会话枚举。
2. 在 `LANGUAGES` 注册代码与本族语名称。无需在界面、CSV或进度模块添加语言判断。
3. 保留模板占位符名称、格式规格和转换标记；可调整词序，不要把运行时名称拼接进待翻译的源文。`csv.field` 特例提供 `label`（源字段标签）与 `field`（英文API键展示）供选择；两种变量均会传入。
4. 缺少或空白译文回退英文；英文也无对应项时保留源文，不丢掉信息。旧拼接消息仍由英文兼容层处理；新动态消息应采用完整模板，避免依赖片段替换。
5. `missing_translations(code)` 列出遗漏的普通源文和以 `@` 标记的消息ID。它以英文目录为对照，不承诺自动扫描所有运行时字符串。
6. spec自动收集 `translations/` 中的Python模块；语言包只随源码／EXE发布，不从网络下载或执行用户提供的语言文件。新增后仍需重新打包。

## 检查

运行 `python scripts/run_tests.py`。测试覆盖注册表、模拟第三语言、英文回退、模板占位符、重复键、条件不变，以及禁止业务／界面模块重新引入按 `zh`／`en` 分支的判断。

还需人工检查长文本、字体、窗口缩放、表头和对话框；从右向左语言需要额外布局适配，不能仅靠翻译文件支持。EXE的 `--smoke-test` 会尝试切换全部已注册语言；详细英文断言仍保留作为现有功能回归基准。
