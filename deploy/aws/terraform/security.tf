resource "aws_security_group" "alb" {
  name        = "${var.environment_name}-alb"
  description = "Public HTTPS entry point for AIR PWA and API."
  vpc_id      = aws_vpc.air.id

  ingress {
    description = "HTTP redirect or explicitly enabled temporary HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.tags, { Name = "${var.environment_name}-alb-sg" })
}

resource "aws_security_group" "ecs" {
  name        = "${var.environment_name}-ecs"
  description = "Private AIR ECS tasks; ingress only from the ALB."
  vpc_id      = aws_vpc.air.id

  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  ingress {
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.tags, { Name = "${var.environment_name}-ecs-sg" })
}

resource "aws_security_group" "postgres" {
  name   = "${var.environment_name}-postgres"
  vpc_id = aws_vpc.air.id
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = merge(local.tags, { Name = "${var.environment_name}-postgres-sg" })
}

resource "aws_security_group" "redis" {
  name   = "${var.environment_name}-redis"
  vpc_id = aws_vpc.air.id
  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = merge(local.tags, { Name = "${var.environment_name}-redis-sg" })
}

resource "aws_security_group" "rabbitmq" {
  name   = "${var.environment_name}-rabbitmq"
  vpc_id = aws_vpc.air.id
  ingress {
    from_port       = 5671
    to_port         = 5671
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = merge(local.tags, { Name = "${var.environment_name}-rabbitmq-sg" })
}

resource "aws_security_group" "efs" {
  name   = "${var.environment_name}-efs"
  vpc_id = aws_vpc.air.id
  ingress {
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = merge(local.tags, { Name = "${var.environment_name}-efs-sg" })
}
