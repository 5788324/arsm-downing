# ARSM 本地资源库规范 v1.0

## 概述

本文档定义 ARSM 项目生态中本地 RJ 资源的存储规范，供 `arsm-downing`（下载器）、`arsm-manager`（资源管理器）、`arsm-player`（播放器）共享使用。

---

## 1. 项目职责边界

| 项目 | 职责 | 读写权限 |
|------|------|----------|
| **arsm-downing** | metadata 获取 + 音频下载 + 断点续传 + `.part` 管理 | RW: downloads, works, metadata_cache |
| **arsm-manager** | 资源库扫描 / 去重 / 迁移 / 校验 / 元数据补全 | RW: works, library_index, metadata_cache |
| **arsm-player** | 读取本地资源库播放音频 | RO: works + 文件夹结构 |

**原则**: 播放器只读，管理器做维护，下载器产生新内容。三者通过 SQLite 共享状态，通过文件夹结构共享文件。

---

## 2. RJ 文件夹命名规范

```
{RJ_ID} {Sanitized_Title}
```

- `RJ_ID`: 8 位数字格式，如 `RJ01588893`
- `Sanitized_Title`: 文件名安全字符串（移除 `< > : " / \ | ? *`，最多 200 字符）
- 示例: `RJ01588893 幼なじみと海の旅にでる話`

---

## 3. 文件夹结构（推荐）

### 3.1 当前结构（v1 — arsm-downing RC7.x）

```
RJ01588893 作品标题/
  cover.jpg
  track_01.mp3
  track_02.mp3
  track_01.mp3.part      ← 断点续传临时文件
  ...
```

### 3.2 推荐结构（v2 — 未来）

```
RJ01588893 作品标题/
  .arsm/
    metadata.json         ← API 原始元数据
    tracks.json           ← 音轨列表
    manifest.json         ← 本地状态清单（见下文）
  cover.jpg
  track_01.mp3
  track_02.mp3
  ...
```

### 3.3 manifest.json 格式

```json
{
  "version": 1,
  "rj_id": "RJ01588893",
  "title": "幼なじみと海の旅にでる話",
  "circle": "Whisp",
  "source": "asmr.one",
  "fetched_at": "2025-01-15T12:00:00Z",
  "tracks": [
    {
      "title": "track_01.mp3",
      "relative_path": "track_01.mp3",
      "size": 12345678,
      "duration_seconds": null,
      "status": "completed"
    }
  ]
}
```

**字段说明**:
- `status`: `completed` | `downloading` | `paused` | `failed` | `missing`
- `relative_path`: 相对于 RJ 文件夹的路径
- `version`: manifest 格式版本号，用于兼容性

---

## 4. SQLite 表结构（共享）

### works
```sql
CREATE TABLE works (
    rj_id TEXT PRIMARY KEY,
    title TEXT,
    circle TEXT,
    downloaded_at TIMESTAMP,
    size_bytes INTEGER DEFAULT 0,
    local_path TEXT,
    cover_url TEXT,
    status TEXT DEFAULT 'completed'
);
```

### downloads
```sql
CREATE TABLE downloads (
    id TEXT PRIMARY KEY,           -- {rj_id}:{hash}
    rj_id TEXT NOT NULL,
    track_title TEXT,
    local_path TEXT,
    status TEXT NOT NULL,          -- queued/paused/downloading/completed/registered/failed
    downloaded_bytes INTEGER DEFAULT 0,
    total_bytes INTEGER DEFAULT 0,
    error TEXT,
    updated_at TIMESTAMP
);
```

### metadata_cache
```sql
CREATE TABLE metadata_cache (
    rj_id TEXT PRIMARY KEY,
    title TEXT,
    circle TEXT,
    cover_url TEXT,
    metadata_json TEXT NOT NULL,   -- API 原始 JSON
    tracks_json TEXT NOT NULL,     -- 音轨列表 JSON
    fetched_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP
);
```

### library_index
```sql
CREATE TABLE library_index (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rj_id TEXT NOT NULL,
    library_path TEXT NOT NULL,
    work_dir TEXT NOT NULL,
    status TEXT DEFAULT 'found',
    size_bytes INTEGER DEFAULT 0,
    file_count INTEGER DEFAULT 0,
    scanned_at TIMESTAMP
);
```

---

## 5. 状态机

### works.status
```
preparing → prepared → (downloaded)
                      → completed
                      → partial
                      → metadata_failed
                      → verified (scan)
                      → external (manual import)
```

### downloads.status
```
queued → downloading → completed → registered
       ↘ paused → queued
       ↘ failed
```

### 跨表一致性规则
1. `works.status = completed` 且 `downloads` 中所有 track 都是 `completed`/`registered`
2. `works.status = verified` → 扫描校验通过，所有文件存在
3. `works.status = partial` → 部分 track 下载失败
4. 终端状态 (`completed`/`verified`/`registered`/`external`) 的 works 不应有 pending downloads

---

## 6. 迁移规则

1. **只迁移终端作品**: `works.status` in (`completed`, `verified`)，且无 pending downloads
2. **禁止迁移**: 含 `queued`/`paused`/`downloading`/`failed` downloads 或 `.part` 文件的作品
3. **迁移时更新**: `works.local_path`, `downloads.local_path`, `library_index.work_dir`
4. **回滚安全**: 迁移失败必须 rollback，不能留半改状态

---

## 7. 代理使用规则

| 场景 | proxy 来源 | 直连 fallback |
|------|-----------|---------------|
| metadata API | `metadata_proxy` | 无 |
| cover 图片 | `cover_proxy` → `metadata_proxy` | 有 |
| 音频下载 | `download_proxy`（默认 null=直连） | `download_fallback_to_proxy=false` 时不 fallback |

**原则**: 默认下载直连。仅当 `download_proxy` 显式设置或 `download_fallback_to_proxy=true` 时才走代理下载。
