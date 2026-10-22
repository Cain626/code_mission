-- 元数据同步水位表：闸门判断「字典新旧」的唯一依据
-- 由 app/scripts/build_meta_knowledge.py 在每次成功同步后写入
USE meta;

CREATE TABLE IF NOT EXISTS meta_sync_state (
    id             INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
    table_name     VARCHAR(128) NOT NULL COMMENT '同步范围：all 表示全量重建，否则为具体表名',
    last_synced_at DATETIME     DEFAULT NULL COMMENT '最近一次成功同步完成的时间',
    status         VARCHAR(32)  DEFAULT NULL COMMENT '最近一次同步状态：ok/failed',
    updated_at     DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录更新时间',
    UNIQUE KEY uk_table_name (table_name)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4 COMMENT ='元数据同步水位';

-- 初始化一行，避免首次查询返回空导致闸门当成「拿不到水位」
INSERT INTO meta_sync_state (table_name, last_synced_at, status)
VALUES ('all', NOW(), 'init')
ON DUPLICATE KEY UPDATE status = 'init';
