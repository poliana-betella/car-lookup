# CAR Lookup

Plugin QGIS que baixa o polígono de um imóvel rural direto do geoserviço público do CAR/SICAR, a partir do código do imóvel — sem precisar navegar pelo mapa nem baixar o shapefile do município inteiro.

## Como funciona

Você informa o código do CAR (com ou sem pontuação). O plugin extrai a UF a partir do código, consulta o WFS público do SICAR (`GetCapabilities`) para descobrir automaticamente a camada correta daquele estado, tenta os nomes de campo mais comuns até achar o que existe naquela camada, baixa a geometria como GeoJSON e carrega direto no projeto do QGIS.

Camada e campo descobertos ficam salvos localmente (nas configurações do QGIS) para as próximas consultas do mesmo estado não precisarem repetir a descoberta. Um comando de menu permite limpar esse cache e redetectar do zero, caso o serviço do CAR mude alguma coisa no futuro.

O plugin também tenta contornar, automaticamente, um problema comum de TLS em geoserviços de governo (cifras/versões mais antigas que o OpenSSL recente recusa por padrão), testando alguns níveis de compatibilidade em sequência até um funcionar. Em todos eles o certificado do servidor continua sendo verificado: se ele não puder ser validado, o plugin avisa e só segue sem verificação se você autorizar (apenas para a sessão atual do QGIS).

## Uso

No menu **Web → CAR Lookup → Baixar imóvel do CAR por código...**, informe o código do imóvel (ex: `SP-3550308-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`). O GeoJSON é salvo em `~/CAR_downloads/` e a camada é adicionada automaticamente ao mapa.

## Instalação

Copie a pasta do plugin para o diretório de plugins do QGIS (`Configurações → Perfis de usuário → Abrir pasta de perfil ativo → python/plugins`) e ative em **Complementos → Gerenciar e Instalar Complementos**.

## Stack

Python puro + API do QGIS (PyQt/qgis.core) — sem dependências externas além do que o próprio QGIS já fornece.
