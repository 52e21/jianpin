# -*- coding: utf-8 -*-
"""评测差异的分类登记表（唯一来源）。

跑批时会出现"从一致变不一致"的用例。为了不把**真缺陷回归**和**标注/词表问题**混在一起，
所有"允许出现"的用例都登记在此，并由各测试脚本共同引用（避免多处维护导致口径漂移）。

判定原则（与用户确认过的口径一致）：
  - 标注口径待复核：我的 ground truth 本身存疑，要人工确认谁对（事项 3 处理）
  - 别名写法缺口：同一技术的不同写法（K8S/Kubernetes 已修；SpringBoot/Spring Boot 待确认批次）
  - 词表覆盖不足：技能词表本来就没有这个技术（Selenium/JMeter），是否扩容由业务定位决定，
                   **不因为评测集而加词**（否则就是对评测集过拟合）
"""

# MySQL 是否应算命中 SQL：这是"上位概念蕴含"问题，不是词形问题。
# 我的标注假设"会 MySQL = 会 SQL"，词边界修复后严格按词形判定为不命中 → 需人工定口径。
KNOWN_LABEL_ISSUES = {"E024"}

# SpringBoot / spring-boot / spring_boot → 已由"写法归一化函数"机械处理（事项 2），
# 不需要枚举别名，因此原先登记的 E029 已修复、从本表移除。
# 缩写与跨技术别名（k8s→Kubernetes 已修）仍走 SKILL_ALIASES 显式枚举。
PENDING_ALIAS: set = set()

# 技能词表覆盖不足（Selenium / JMeter 不在 SKILL_KEYWORDS 中）。
KNOWN_DICT_GAPS = {"E056"}

ALLOWED_REGRESSIONS = KNOWN_LABEL_ISSUES | PENDING_ALIAS | KNOWN_DICT_GAPS
