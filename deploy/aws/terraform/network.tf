locals {
  azs = slice(data.aws_availability_zones.available.names, 0, 2)
  tags = {
    Product     = "AIR"
    Environment = var.environment_name
    ManagedBy   = "Terraform"
    Deployment  = "aws-private-single"
  }
}

resource "aws_vpc" "air" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = merge(local.tags, { Name = "${var.environment_name}-vpc" })
}

resource "aws_internet_gateway" "air" {
  vpc_id = aws_vpc.air.id
  tags   = merge(local.tags, { Name = "${var.environment_name}-igw" })
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.air.id
  cidr_block              = var.public_subnet_cidrs[count.index]
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true
  tags = merge(local.tags, {
    Name = "${var.environment_name}-public-${count.index + 1}"
    Tier = "public"
  })
}

resource "aws_subnet" "private" {
  count                   = 2
  vpc_id                  = aws_vpc.air.id
  cidr_block              = var.private_subnet_cidrs[count.index]
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = false
  tags = merge(local.tags, {
    Name = "${var.environment_name}-private-${count.index + 1}"
    Tier = "private"
  })
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.air.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.air.id
  }
  tags = merge(local.tags, { Name = "${var.environment_name}-public-rt" })
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_eip" "nat" {
  count  = 2
  domain = "vpc"
  tags   = merge(local.tags, { Name = "${var.environment_name}-nat-eip-${count.index + 1}" })
}

resource "aws_nat_gateway" "air" {
  count         = 2
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id
  depends_on    = [aws_internet_gateway.air]
  tags          = merge(local.tags, { Name = "${var.environment_name}-nat-${count.index + 1}" })
}

resource "aws_route_table" "private" {
  count  = 2
  vpc_id = aws_vpc.air.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.air[count.index].id
  }
  tags = merge(local.tags, { Name = "${var.environment_name}-private-rt-${count.index + 1}" })
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}
