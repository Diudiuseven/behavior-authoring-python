# Behavior Authoring Service

行为定义的在线编写与版本化发布服务。设计者反复修改行为图草稿，校验通过后
发布为不可变版本；运行时只读取已发布版本。

## 运行

```bash
uv run python main.py        # 启动 HTTP 服务（默认 127.0.0.1:8000）
uv run pytest                # 运行全部测试
```

调用接口时通过 `X-User` 请求头标识操作者。

## 核心概念与版本语义

### 草稿（Draft）

- 每个行为图（`graph_id`）有一份草稿，可反复保存，允许保存非法的中间状态。
- 草稿携带单调递增的 `revision`，保存时必须带上编辑所基于的
  `expected_revision`（乐观并发控制）。
- 两个编辑者同时保存时，先提交者成功；冲突方收到 409 及可解释信息
  （谁把草稿推进到了哪个 revision），其修改**不会被静默覆盖**，
  需拉取最新草稿合并后以新 revision 重试。

### 发布版本（Published Version）

- 发布把当前草稿固化为**不可变**版本，版本号从 1 开始单调递增，长期共存。
- 发布是**原子**的：先完成结构迁移、成组校验与编译，全部成功后存储层才在
  单把锁内写入版本并推进 `latest` 指针。任一步失败都不会留下半个版本，
  消费者在发布完成前只能读到上一个完整版本。
- 发布时图定义会被规范化到当前 schema 版本后固化。
- 运行时按 `(graph_id, version)` 读取，内容与编译产物哈希与发布时完全一致，
  重复读取可复现。
- 回滚不是修改历史，而是**以历史版本内容发布一个新版本**
  （`rollback_of` 记录来源版本号），历史版本保持不变。

### 结构演进（Schema Migration）

- 图定义带 `schema_version`。当前为 v2；v1 用 `"$bb:<key>"` 字符串参数表示
  黑板引用且无显式 `param_refs`。
- 旧结构版本在**读取路径的副本上**迁移到新结构，已发布内容绝不被修改。
- 无法迁移（来自未来的版本、无法识别的版本）时返回明确错误说明原因。

### 校验（Validation）

- 节点、连线、黑板键、参数引用**成组校验**：连线端点必须存在、每个节点
  至多一个父节点、叶子/组合节点的子节点约束、参数引用必须指向已声明的
  黑板键、必须有且仅有一个 root、无环且从 root 可达。
- 一次校验返回**全部**问题，每个问题包含稳定的错误码（`code`）、
  元素类别（`element_kind`）、具体元素标识（`element_id`）与原因说明，
  可定位到具体节点/连线/键/参数引用。

### 编译缓存（Compilation）

- 编译产物（拓扑序、邻接表、索引）按图内容的 SHA-256 哈希缓存。
- 内容哈希与节点/连线在输入中的排列顺序无关：定义未变则哈希不变，
  重复编译直接复用缓存，结果一致且确定。

### 权限与审计

| 角色       | 编辑草稿 | 发布 | 回滚 |
|------------|----------|------|------|
| `editor`   | ✓        |      |      |
| `publisher`| ✓        | ✓    |      |
| `admin`    | ✓        | ✓    | ✓    |

- 越权操作被拒绝（403），允许与拒绝都会写入审计日志
  （操作者、动作、图、版本、结果、原因、时间），可通过 `GET /audit` 查询。

## 发布流程

```
POST /graphs/{id}/draft                 # 1. 创建草稿
PUT  /graphs/{id}/draft                 # 2. 反复保存（携带 expected_revision）
POST /graphs/{id}/draft/validate        # 3. 随时校验，查看全部问题
POST /graphs/{id}/publish               # 4. 校验+编译+原子写入，得到不可变版本
GET  /graphs/{id}/versions/{v}          # 5. 运行时按版本读取（可复现）
POST /graphs/{id}/rollback/{v}          # 6. 需要时回滚（admin，产生新版本）
```

## HTTP 接口一览

| 方法与路径 | 说明 | 主要错误码 |
|---|---|---|
| `POST /graphs/{id}/draft` | 创建草稿 | 401 |
| `GET /graphs/{id}/draft` | 读取草稿（含当前 revision） | 404 |
| `PUT /graphs/{id}/draft` | 保存草稿（乐观并发） | 409 冲突 / 403 |
| `POST /graphs/{id}/draft/validate` | 成组校验草稿 | 404 |
| `POST /graphs/{id}/publish` | 发布草稿为新版本 | 422 校验失败 / 403 |
| `GET /graphs/{id}/versions` | 列出全部版本 | |
| `GET /graphs/{id}/versions/{v}` | 按版本读取（含编译产物哈希） | 404 / 422 无法迁移 |
| `GET /graphs/{id}/latest` | 读取最新完整版本 | 404 |
| `POST /graphs/{id}/rollback/{v}` | 回滚（发布历史内容为新版本） | 403 / 404 |
| `GET /audit` | 查询审计日志 | |

## 代码结构

```
behavior_authoring/
  models.py      # 领域类型：图、草稿、版本、校验问题、审计记录、异常
  validation.py  # 成组校验（定位到具体元素）
  storage.py     # 内存存储：乐观并发 + 原子发布 + 不可变版本
  compiler.py    # 编译与内容哈希缓存（确定性）
  migration.py   # 旧 schema 迁移（只动副本，不动已发布版本）
  auth.py        # 角色权限与审计日志
  service.py     # 应用服务门面，编排以上组件
  api.py         # FastAPI HTTP 层
tests/           # 校验失败、并发保存、版本共存、结构迁移、越权、编译缓存
```
