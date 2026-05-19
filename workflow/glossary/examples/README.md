# 示例说明

本目录用于放置脱敏后的样例语言表或样例输出。

当前仓库默认不提交真实项目语言表，原因：

- 客户数据通常不可公开
- 语言表常包含未上线内容
- 术语提取逻辑可以用测试数据覆盖

## 推荐本地验证方式

### 1. 准备一份最小表头的 Excel

表头示例：

```text
ID | cn | en
```

### 2. 执行命令

```bash
python scripts/extract_glossary.py /path/to/language_table.xlsx
```

### 3. 检查输出

- `*_glossary_details_YYYYMMDD.xlsx`
- `*_ID_CN_EN_EN2_YYYYMMDD.xlsx`
- `data/experience/curated_terms.json` 是否保留人工确认规则
- `data/experience/observed_terms.json` 是否正确积累观察结果

### 4. 运行回归 harness

```bash
python scripts/run_glossary_harness.py \
  fixtures/core_regression.json \
  fixtures/observation_feedback_regression.json
```

## 适合做样例的数据类型

- 脱敏后的功能按钮词
- 公共系统提示词
- 人工构造的小型测试语言表
