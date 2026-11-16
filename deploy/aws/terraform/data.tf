resource "random_password" "postgres" {
  length  = 32
  special = false
}
resource "random_password" "redis" {
  length  = 48
  special = false
}
resource "random_password" "rabbitmq" {
  length  = 32
  special = false
}
resource "random_password" "jwt" {
  length  = 64
  special = false
}
resource "random_password" "credential_key" {
  length  = 64
  special = false
}
resource "random_password" "admin_api_key" {
  length  = 48
  special = false
}

resource "aws_db_subnet_group" "air" {
  name       = "${var.environment_name}-db"
  subnet_ids = aws_subnet.private[*].id
  tags       = local.tags
}

resource "aws_db_instance" "air" {
  identifier                 = "${var.environment_name}-postgres"
  engine                     = "postgres"
  engine_version             = var.postgres_engine_version
  instance_class             = var.postgres_instance_class
  allocated_storage          = var.postgres_allocated_storage
  storage_type               = "gp3"
  storage_encrypted          = true
  db_name                    = "air"
  username                   = "air"
  password                   = random_password.postgres.result
  port                       = 5432
  db_subnet_group_name       = aws_db_subnet_group.air.name
  vpc_security_group_ids     = [aws_security_group.postgres.id]
  multi_az                   = var.postgres_multi_az
  publicly_accessible        = false
  backup_retention_period    = var.backup_retention_days
  deletion_protection        = var.postgres_deletion_protection
  skip_final_snapshot        = false
  final_snapshot_identifier  = "${var.environment_name}-postgres-final"
  auto_minor_version_upgrade = true
  apply_immediately          = false
  tags                       = local.tags
}

resource "aws_elasticache_subnet_group" "air" {
  name       = "${var.environment_name}-redis"
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_elasticache_replication_group" "air" {
  replication_group_id       = "${var.environment_name}-redis"
  description                = "AIR private single-tenant Redis"
  engine                     = "redis"
  engine_version             = var.redis_engine_version
  node_type                  = var.redis_node_type
  port                       = 6379
  num_cache_clusters         = 2
  automatic_failover_enabled = true
  multi_az_enabled           = true
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  auth_token                 = random_password.redis.result
  subnet_group_name          = aws_elasticache_subnet_group.air.name
  security_group_ids         = [aws_security_group.redis.id]
  apply_immediately          = false
  tags                       = local.tags
}

resource "aws_mq_broker" "air" {
  broker_name                = "${var.environment_name}-rabbitmq"
  engine_type                = "RabbitMQ"
  engine_version             = var.rabbitmq_engine_version
  host_instance_type         = var.rabbitmq_instance_type
  deployment_mode            = "CLUSTER_MULTI_AZ"
  publicly_accessible        = false
  auto_minor_version_upgrade = true
  subnet_ids                 = aws_subnet.private[*].id
  security_groups            = [aws_security_group.rabbitmq.id]
  user {
    username = "air"
    password = random_password.rabbitmq.result
  }
  logs {
    general = true
  }
  tags = local.tags
}

resource "aws_efs_file_system" "air" {
  encrypted        = true
  performance_mode = "generalPurpose"
  throughput_mode  = "elastic"
  tags             = merge(local.tags, { Name = "${var.environment_name}-efs" })
}

resource "aws_efs_backup_policy" "air" {
  file_system_id = aws_efs_file_system.air.id
  backup_policy {
    status = "ENABLED"
  }
}

resource "aws_efs_mount_target" "air" {
  count           = 2
  file_system_id  = aws_efs_file_system.air.id
  subnet_id       = aws_subnet.private[count.index].id
  security_groups = [aws_security_group.efs.id]
}

resource "aws_efs_access_point" "air" {
  file_system_id = aws_efs_file_system.air.id
  posix_user {
    uid = 1000
    gid = 1000
  }
  root_directory {
    path = "/air"
    creation_info {
      owner_uid   = 1000
      owner_gid   = 1000
      permissions = "0750"
    }
  }
  tags = local.tags
}

resource "aws_s3_bucket" "air" {
  bucket_prefix = "${var.environment_name}-data-"
  force_destroy = false
  tags          = local.tags
}
resource "aws_s3_bucket_public_access_block" "air" {
  bucket                  = aws_s3_bucket.air.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_versioning" "air" {
  bucket = aws_s3_bucket.air.id
  versioning_configuration {
    status = "Enabled"
  }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "air" {
  bucket = aws_s3_bucket.air.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_ecr_repository" "backend" {
  name                 = "${var.environment_name}/backend"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "AES256"
  }
  tags = local.tags
}
resource "aws_ecr_repository" "pwa" {
  name                 = "${var.environment_name}/pwa"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "AES256"
  }
  tags = local.tags
}

resource "aws_secretsmanager_secret" "postgres" {
  name = "${var.environment_name}/postgres-url"
  tags = local.tags
}
resource "aws_secretsmanager_secret_version" "postgres" {
  secret_id     = aws_secretsmanager_secret.postgres.id
  secret_string = "postgresql://air:${random_password.postgres.result}@${aws_db_instance.air.address}:5432/air"
}
resource "aws_secretsmanager_secret" "redis" {
  name = "${var.environment_name}/redis-url"
  tags = local.tags
}
resource "aws_secretsmanager_secret_version" "redis" {
  secret_id     = aws_secretsmanager_secret.redis.id
  secret_string = "rediss://:${random_password.redis.result}@${aws_elasticache_replication_group.air.primary_endpoint_address}:6379/0"
}
resource "aws_secretsmanager_secret" "rabbitmq" {
  name = "${var.environment_name}/rabbitmq-url"
  tags = local.tags
}
resource "aws_secretsmanager_secret_version" "rabbitmq" {
  secret_id     = aws_secretsmanager_secret.rabbitmq.id
  secret_string = "amqps://air:${random_password.rabbitmq.result}@${trimprefix(aws_mq_broker.air.instances[0].endpoints[0], "amqps://")}/"
}
resource "aws_secretsmanager_secret" "jwt" {
  name = "${var.environment_name}/jwt-secret"
  tags = local.tags
}
resource "aws_secretsmanager_secret_version" "jwt" {
  secret_id     = aws_secretsmanager_secret.jwt.id
  secret_string = random_password.jwt.result
}
resource "aws_secretsmanager_secret" "credential_key" {
  name = "${var.environment_name}/credential-key"
  tags = local.tags
}
resource "aws_secretsmanager_secret_version" "credential_key" {
  secret_id     = aws_secretsmanager_secret.credential_key.id
  secret_string = random_password.credential_key.result
}
resource "aws_secretsmanager_secret" "admin_api_key" {
  name = "${var.environment_name}/admin-api-key"
  tags = local.tags
}
resource "aws_secretsmanager_secret_version" "admin_api_key" {
  secret_id     = aws_secretsmanager_secret.admin_api_key.id
  secret_string = random_password.admin_api_key.result
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/air/${var.environment_name}/api"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}
resource "aws_cloudwatch_log_group" "worker" {
  name              = "/air/${var.environment_name}/worker"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}
resource "aws_cloudwatch_log_group" "pwa" {
  name              = "/air/${var.environment_name}/pwa"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}
