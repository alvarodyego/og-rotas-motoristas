# Rotas otimizadas para motoristas (PathFind -> GitHub Pages)

Publica automaticamente, todo dia, um link por rota (`RT001001`, `RT001002`,
...) que o motorista abre no celular e ve a sequencia de entrega otimizada
por proximidade geografica, com mapa.

**AVISO:** a otimizacao considera **somente distancia geografica**
(vizinho mais proximo + Haversine). Ela **nao** leva em conta janela de
horario nem prazo de entrega combinado com o cliente. Esse aviso tambem
aparece nas paginas publicadas.

**Sem senha:** qualquer pessoa com o link de uma rota consegue ver nomes de
clientes, enderecos e a sequencia de entrega. Os links nao sao facilmente
adivinhaveis (dependem do codigo exato da rota do dia), mas nao ha nenhuma
autenticacao real.

## Como funciona

```
PathFind exporta .txt -> pasta do Google Drive -> watch_and_publish.py detecta
   -> parsing.py + route_optimizer.py processam
   -> site_generator.py gera docs/index.html e docs/rotas/RTxxxxxx.html
   -> git commit + push -> GitHub Pages publica em ~1 minuto
```

## Configuracao inicial (uma unica vez)

1. **Crie o repositorio no GitHub** (pelo navegador, ja logado na sua conta):
   - New repository -> nome (ex: `og-rotas-motoristas`) -> **Public** -> sem README -> Create.
   - Copie a URL do repositorio (ex: `https://github.com/SEU_USUARIO/og-rotas-motoristas.git`).

2. **Ligue o repositorio local a esse repositorio remoto** (rode uma vez, na pasta deste projeto):
   ```bash
   git init
   git add .
   git commit -m "Primeira versao do sistema de rotas"
   git branch -M main
   git remote add origin https://github.com/SEU_USUARIO/og-rotas-motoristas.git
   git push -u origin main
   ```
   No primeiro `push`, o Git Credential Manager do Windows deve abrir uma
   janela do navegador pedindo para voce fazer login no GitHub. Faca login
   ali (nunca digite a senha em outro lugar) — depois disso o Windows
   lembra e os proximos `push` acontecem sem pedir nada.

3. **Ative o GitHub Pages** no site do GitHub:
   - No repositorio -> Settings -> Pages -> Source: **Deploy from a branch**
     -> Branch: `main`, pasta **`/docs`** -> Save.
   - Depois de alguns minutos, o site fica disponivel em
     `https://SEU_USUARIO.github.io/og-rotas-motoristas/`.

4. **Descubra o caminho local da pasta do Google Drive** que recebe o `.txt`
   exportado do PathFind (algo como `C:\Users\...\Google Drive\...` ou uma
   unidade `G:\Meu Drive\...`).

## Uso diario

Duas opcoes, escolha uma:

- **Deixar rodando automaticamente:** clique duas vezes em
  `iniciar_vigilancia.bat`, cole o caminho da pasta do Drive quando pedido, e
  deixe a janela aberta. Sempre que a PathFind deixar um novo arquivo
  `rastro_rotas*.txt` nessa pasta, o site e atualizado e publicado sozinho
  (checagem a cada 30 segundos).

- **Rodar uma vez manualmente:**
  ```bash
  python watch_and_publish.py "C:\caminho\da\pasta\do\Drive"
  ```
  e deixar aberto durante o expediente, ou usar o Agendador de Tarefas do
  Windows para iniciar esse comando automaticamente todo dia.

## Arquivos

- `parsing.py` — le o `.txt` de largura fixa do PathFind e extrai cada entrega.
- `route_optimizer.py` — Haversine + vizinho mais proximo, compara distancia
  original vs. otimizada.
- `site_generator.py` — gera `docs/index.html` (lista de rotas do dia) e
  `docs/rotas/RTxxxxxx.html` (pagina do motorista, com mapa Leaflet).
- `watch_and_publish.py` — vigia a pasta do Drive e publica automaticamente.
- `docs/` — pasta servida pelo GitHub Pages (nao edite a mao, e regerada
  a cada execucao).
