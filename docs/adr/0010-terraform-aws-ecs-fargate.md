# ADR-0010: Infra como código com Terraform, alvo AWS ECS Fargate

**Status.** Aceito.

## Contexto

Quero demonstrar CD/IaC real sem quebrar o requisito de "rodar localmente" e sem custo/complexidade
desnecessários.

## Decisão

Terraform provisionando na AWS: ECR (imagem), ECS Fargate (serving), ALB (entrada), ElastiCache
(Redis). Ambiente dev mínimo, com `terraform destroy` documentado. O run local via docker-compose
continua sendo o caminho garantido de avaliação.

## Alternativas

- *EKS (Kubernetes):* mais poder, mas overkill e mais caro/complexo para um serviço só neste
  escopo.
- *Pulumi:* boa opção, mas Terraform é o que se domina e defende melhor aqui.
- *Sem IaC (só local):* mais seguro, porém perde a demonstração de maturidade de plataforma.

## Consequências

- (+) Mostra CD/IaC de verdade, versionado e destruível.
- (+) Fargate: sem gerenciar nós, simples para um serviço.
- (−) Custo de nuvem se ficar de pé (mitigado por dev mínimo + destroy); o avaliador não precisa
  aplicar, o local basta.
