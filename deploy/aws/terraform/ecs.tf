resource "aws_ecs_cluster" "air" {
  name = var.environment_name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
  tags = local.tags
}

resource "aws_iam_role" "ecs_execution" {
  name = "${var.environment_name}-ecs-execution"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
  tags = local.tags
}
resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}
resource "aws_iam_role_policy" "ecs_secrets" {
  name = "${var.environment_name}-read-runtime-secrets"
  role = aws_iam_role.ecs_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["secretsmanager:GetSecretValue"]
      Resource = [
        aws_secretsmanager_secret.postgres.arn,
        aws_secretsmanager_secret.redis.arn,
        aws_secretsmanager_secret.rabbitmq.arn,
        aws_secretsmanager_secret.rabbitmq_admin_password.arn,
        aws_secretsmanager_secret.jwt.arn,
        aws_secretsmanager_secret.credential_key.arn,
        aws_secretsmanager_secret.admin_api_key.arn
      ]
    }]
  })
}
resource "aws_iam_role" "ecs_task" {
  name               = "${var.environment_name}-ecs-task"
  assume_role_policy = aws_iam_role.ecs_execution.assume_role_policy
  tags               = local.tags
}
resource "aws_iam_role_policy" "ecs_task_storage" {
  name = "${var.environment_name}-efs-s3-access"
  role = aws_iam_role.ecs_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["elasticfilesystem:ClientMount", "elasticfilesystem:ClientWrite", "elasticfilesystem:ClientRootAccess"], Resource = aws_efs_file_system.air.arn, Condition = { StringEquals = { "elasticfilesystem:AccessPointArn" = aws_efs_access_point.air.arn } } },
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], Resource = "${aws_s3_bucket.air.arn}/*" },
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.air.arn },
      { Effect = "Allow", Action = ["s3:CreateBucket"], Resource = "*" },
      { Effect = "Allow", Action = ["s3:PutBucketPublicAccessBlock", "s3:PutEncryptionConfiguration", "s3:PutBucketVersioning", "s3:PutBucketTagging", "s3:GetBucketLocation", "s3:ListBucket"], Resource = "arn:aws:s3:::${local.tenant_bucket_prefix}*" },
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"], Resource = "arn:aws:s3:::${local.tenant_bucket_prefix}*/*" },
      { Effect = "Allow", Action = ["secretsmanager:CreateSecret", "secretsmanager:DescribeSecret", "secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue", "secretsmanager:TagResource"], Resource = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${var.tenant_secrets_prefix}/*" }
    ]
  })
}

resource "aws_lb" "air" {
  name                       = substr("${var.environment_name}-alb", 0, 32)
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.alb.id]
  subnets                    = aws_subnet.public[*].id
  enable_deletion_protection = true
  tags                       = local.tags
}
resource "aws_lb_target_group" "pwa" {
  name        = substr("${var.environment_name}-pwa", 0, 32)
  port        = 8080
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.air.id
  health_check {
    path    = "/health"
    matcher = "200-399"
  }
  tags = local.tags
}
resource "aws_lb_target_group" "api" {
  name        = substr("${var.environment_name}-api", 0, 32)
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.air.id
  health_check {
    path    = "/health"
    matcher = "200-399"
  }
  tags = local.tags
}
resource "aws_lb_listener" "https" {
  count             = var.acm_certificate_arn != "" ? 1 : 0
  load_balancer_arn = aws_lb.air.arn
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = var.acm_certificate_arn
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.pwa.arn
  }
}
resource "aws_lb_listener" "http" {
  count             = var.acm_certificate_arn == "" && var.allow_http ? 1 : 0
  load_balancer_arn = aws_lb.air.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.pwa.arn
  }
}
resource "aws_lb_listener_rule" "api_https" {
  count        = var.acm_certificate_arn != "" ? 1 : 0
  listener_arn = aws_lb_listener.https[0].arn
  priority     = 10
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
  condition {
    path_pattern {
      values = ["/api/*", "/health", "/ready", "/openapi.json", "/docs*"]
    }
  }
}
resource "aws_lb_listener_rule" "api_http" {
  count        = var.acm_certificate_arn == "" && var.allow_http ? 1 : 0
  listener_arn = aws_lb_listener.http[0].arn
  priority     = 10
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
  condition {
    path_pattern {
      values = ["/api/*", "/health", "/ready", "/openapi.json", "/docs*"]
    }
  }
}

resource "aws_ecs_task_definition" "api" {
  count                    = var.deploy_services ? 1 : 0
  family                   = "${var.environment_name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.api_cpu)
  memory                   = tostring(var.api_memory)
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn
  volume {
    name = "air-data"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.air.id
      transit_encryption = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.air.id
        iam             = "ENABLED"
      }
    }
  }
  container_definitions = jsonencode([{
    name         = "air-api"
    image        = var.backend_image_uri
    essential    = true
    portMappings = [{ containerPort = 8000, hostPort = 8000, protocol = "tcp" }]
    environment = [
      { name = "AIR_DEPLOYMENT_PROFILE", value = var.deployment_profile },
      { name = "AIR_DEPLOYMENT_MODE", value = "aws" },
      { name = "AIR_TENANCY_MODE", value = var.tenancy_mode },
      { name = "AIR_RABBITMQ_MANAGEMENT_URL", value = replace(replace(aws_mq_broker.air.instances[0].endpoints[0], "amqps://", "https://"), ":5671", ":15671") },
      { name = "AIR_RABBITMQ_ADMIN_USER", value = "air" },
      { name = "AIR_TENANT_S3_BUCKET_PREFIX", value = local.tenant_bucket_prefix },
      { name = "AIR_TENANT_SECRETS_PREFIX", value = var.tenant_secrets_prefix },
    ]
    secrets = [
      { name = "AIR_DATABASE_URL", valueFrom = aws_secretsmanager_secret.postgres.arn },
      { name = "AIR_CUSTOMER_DATABASE_URL", valueFrom = aws_secretsmanager_secret.postgres.arn },
      { name = "AIR_ACCOUNT_DATABASE_URL", valueFrom = aws_secretsmanager_secret.postgres.arn },
      { name = "AIR_CREDENTIAL_DATABASE_URL", valueFrom = aws_secretsmanager_secret.postgres.arn },
      { name = "AIR_REDIS_URL", valueFrom = aws_secretsmanager_secret.redis.arn },
      { name = "AIR_RABBITMQ_URL", valueFrom = aws_secretsmanager_secret.rabbitmq.arn },
      { name = "AIR_RABBITMQ_ADMIN_PASSWORD", valueFrom = aws_secretsmanager_secret.rabbitmq_admin_password.arn },
      { name = "AIR_JWT_SECRET", valueFrom = aws_secretsmanager_secret.jwt.arn },
      { name = "AIR_CREDENTIAL_KEY", valueFrom = aws_secretsmanager_secret.credential_key.arn },
      { name = "AIR_ADMIN_API_KEY", valueFrom = aws_secretsmanager_secret.admin_api_key.arn }
    ]
    mountPoints      = [{ sourceVolume = "air-data", containerPath = "/var/lib/air", readOnly = false }]
    logConfiguration = { logDriver = "awslogs", options = { awslogs-group = aws_cloudwatch_log_group.api.name, awslogs-region = var.aws_region, awslogs-stream-prefix = "api" } }
    healthCheck      = { command = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)\""], interval = 30, timeout = 5, retries = 3, startPeriod = 30 }
  }])
  lifecycle {
    precondition {
      condition     = var.backend_image_uri != ""
      error_message = "backend_image_uri is required when deploy_services=true."
    }
  }
  tags = local.tags
}
resource "aws_ecs_task_definition" "worker" {
  count                    = var.deploy_services ? 1 : 0
  family                   = "${var.environment_name}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.worker_cpu)
  memory                   = tostring(var.worker_memory)
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn
  volume {
    name = "air-data"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.air.id
      transit_encryption = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.air.id
        iam             = "ENABLED"
      }
    }
  }
  container_definitions = jsonencode([{
    name      = "air-workflow-worker"
    image     = var.backend_image_uri
    command   = ["python", "-m", "app.workflow_worker"]
    essential = true
    environment = [
      { name = "AIR_DEPLOYMENT_PROFILE", value = var.deployment_profile },
      { name = "AIR_DEPLOYMENT_MODE", value = "aws" },
      { name = "AIR_TENANCY_MODE", value = var.tenancy_mode },
    ]
    secrets = [
      { name = "AIR_DATABASE_URL", valueFrom = aws_secretsmanager_secret.postgres.arn },
      { name = "AIR_CUSTOMER_DATABASE_URL", valueFrom = aws_secretsmanager_secret.postgres.arn },
      { name = "AIR_ACCOUNT_DATABASE_URL", valueFrom = aws_secretsmanager_secret.postgres.arn },
      { name = "AIR_CREDENTIAL_DATABASE_URL", valueFrom = aws_secretsmanager_secret.postgres.arn },
      { name = "AIR_CREDENTIAL_KEY", valueFrom = aws_secretsmanager_secret.credential_key.arn },
      { name = "AIR_REDIS_URL", valueFrom = aws_secretsmanager_secret.redis.arn },
      { name = "AIR_RABBITMQ_URL", valueFrom = aws_secretsmanager_secret.rabbitmq.arn }
    ]
    mountPoints      = [{ sourceVolume = "air-data", containerPath = "/var/lib/air", readOnly = false }]
    logConfiguration = { logDriver = "awslogs", options = { awslogs-group = aws_cloudwatch_log_group.worker.name, awslogs-region = var.aws_region, awslogs-stream-prefix = "worker" } }
  }])
  lifecycle {
    precondition {
      condition     = var.backend_image_uri != ""
      error_message = "backend_image_uri is required when deploy_services=true."
    }
  }
  tags = local.tags
}
resource "aws_ecs_task_definition" "pwa" {
  count                    = var.deploy_services ? 1 : 0
  family                   = "${var.environment_name}-pwa"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.pwa_cpu)
  memory                   = tostring(var.pwa_memory)
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn
  container_definitions = jsonencode([{
    name             = "air-pwa"
    image            = var.pwa_image_uri
    essential        = true
    portMappings     = [{ containerPort = 8080, hostPort = 8080, protocol = "tcp" }]
    logConfiguration = { logDriver = "awslogs", options = { awslogs-group = aws_cloudwatch_log_group.pwa.name, awslogs-region = var.aws_region, awslogs-stream-prefix = "pwa" } }
  }])
  lifecycle {
    precondition {
      condition     = var.pwa_image_uri != ""
      error_message = "pwa_image_uri is required when deploy_services=true."
    }
  }
  tags = local.tags
}

resource "aws_ecs_service" "api" {
  count            = var.deploy_services ? 1 : 0
  name             = "air-api"
  cluster          = aws_ecs_cluster.air.id
  task_definition  = aws_ecs_task_definition.api[0].arn
  desired_count    = 1
  launch_type      = "FARGATE"
  platform_version = "LATEST"
  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "air-api"
    container_port   = 8000
  }
  depends_on = [aws_lb_listener.https, aws_lb_listener.http, aws_iam_role_policy_attachment.ecs_execution, aws_iam_role_policy.ecs_secrets]
  tags       = local.tags
}
resource "aws_ecs_service" "worker" {
  count            = var.deploy_services ? 1 : 0
  name             = "air-workflow-worker"
  cluster          = aws_ecs_cluster.air.id
  task_definition  = aws_ecs_task_definition.worker[0].arn
  desired_count    = 1
  launch_type      = "FARGATE"
  platform_version = "LATEST"
  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false
  }
  depends_on = [aws_iam_role_policy_attachment.ecs_execution, aws_iam_role_policy.ecs_secrets]
  tags       = local.tags
}
resource "aws_ecs_service" "pwa" {
  count            = var.deploy_services ? 1 : 0
  name             = "air-pwa"
  cluster          = aws_ecs_cluster.air.id
  task_definition  = aws_ecs_task_definition.pwa[0].arn
  desired_count    = 1
  launch_type      = "FARGATE"
  platform_version = "LATEST"
  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.pwa.arn
    container_name   = "air-pwa"
    container_port   = 8080
  }
  depends_on = [aws_lb_listener.https, aws_lb_listener.http, aws_iam_role_policy_attachment.ecs_execution]
  tags       = local.tags
}
