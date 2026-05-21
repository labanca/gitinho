> Esse foi uma tentantiva de criar um agente que tivesse todo conhecimento da nossa organização e conseguisse responder perguntas, em linguagem natural, sobre
  ela com precisão. Não é mandatário manter nada da stack ou dos arquivos atuais, caso substituir seja melhor. Sendo assim.

  Esse agente deve ser capaz de fazer buscas complexas na API do github e responder perguntas como:

  - qual ultimo issue criado pelo usuário X?
  - quantos PR/issues/repostas foram feitas pelo usuário Y este mes?
  - Quantos datapackages possuimos em nossa organização? Quantos são públicos e são privados?
  - crie uma relação de todos os repositorios que temos com as seguintes informações: campo A, campo B, Campo C... Converta essa relação para uma planilha
  excel.
  - qual ultimo comiit feito pelo usuário Z?
  - qual ultimo commit feito no repositorio A?
  - qual ultimo commit criado pelo usuário X no repositorio B?
  - Quantos PR temos abertos em todos nossos respositórios?
  - Quantos Repositórios nossos não recebem nenhuma atualização a mais de n dias/meses/anos?
  - quais repositorios tem mais de 1 branch?
  - me de uma relação de todos os usuários da organização relacionando para cada um a quantidade de issue criados, commit feitos, PR feitos, repostas a issue
  feitas, disussões criadas, respostas a discussões feitas e data da última interação dele com nossa org.

  O agente deve ser capaz de reponder a essas perguntas com precisão, e não aprximar nada. Também deve ser capaz de manter memoria da seção e separar chats e
  seções passadas da mesma forma que chat de IA geralmente fazem (a interface deve ser semelhante a chatGPT, Grok, Gemini, etc., mas somente no que tange a
  interação com usuário.

  Importante.
  - Por padrão o agente somente fará operações de leitura, apesar de requerer o token e permissões necessárias para executar as tarefas acima listadas. POde
  usar qualquer modelos adequados que estejam presentes no plano Azure Foundry da Microsoft, pois possuo assinatura corporativa do mesmo. Custo não é
  problema, mas precisão e assertividade sim.

  - Em um momento futuro o repositório permitira ações de escrita, mas isso ficara para uma segunda fase. Construa a primeira fase pensando nisso.
  - o agente deve ser capaz de utilizar MCP e tools.
  - Pode me fazer todas as peruntas necessárias para construção, mas faça todas de uma vez.
  - Registre tudo em um documento de planejamento e já comece a implementação
  - Implemente segurança forte para impedir que o agente possa destruir ativos da organização ou expor informações da mesma.
