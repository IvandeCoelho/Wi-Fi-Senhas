# Wi-Fi Senhas

**Visualize, gerencie e organize as redes Wi-Fi salvas no seu computador.**

O **Wi-Fi Senhas** é um aplicativo desenvolvido em Python que permite visualizar e gerenciar redes Wi-Fi, incluindo suas respectivas senhas armazenadas no computador.

Com uma interface gráfica simples e intuitiva, oferece recursos para listar, importar, exportar, conectar, editar e excluir redes Wi-Fi.

## Funcionalidades

- **Listar redes Wi-Fi:** exibe as redes salvas no computador e suas respectivas senhas.
- **Identificar status:** informa se a rede está conectada atualmente, salva no computador ou apenas importada.
- **Conectar à rede:** permite conectar a redes importadas que ainda não estão configuradas no computador.
- **Editar senhas:** possibilita alterar a senha de redes Wi-Fi.
- **Excluir redes:** remove redes Wi-Fi armazenadas no computador.
- **Exportar listas:** permite salvar as informações das redes para backup ou transferência.
- **Importar listas:** carrega redes previamente exportadas para facilitar a transferência de configurações.

## Compatibilidade

| Sistema operacional | Listar redes | Importar / Exportar | Conectar | Editar / Excluir |
| ------------------- | :----------: | :-----------------: | :------: | :--------------: |
| Windows 10/11       |      ✅      |         ✅          |    ✅    |        ✅        |
| Linux               |      ✅      |         ✅          |    ❌    |        ❌        |
| macOS               |      ✅      |         ✅          |    ❌    |        ❌        |

**Observação:** As funcionalidades de conexão, edição e exclusão estão implementadas somente para Windows. No Linux e macOS, estão disponíveis apenas a listagem, importação e exportação de redes.

## Requisitos

- Python 3.8 ou superior.
- Tkinter (normalmente incluído na instalação do Python).
- Windows 10/11 para utilizar todas as funcionalidades.

Não é necessário instalar bibliotecas adicionais, desde que o Tkinter esteja disponível.

## Instalação e execução

**1. Clone o repositório:**

```bash
git clone https://github.com/IvandeCoelho/Wi-Fi-Senhas.git
```

**2. Acesse a pasta do projeto:**

```bash
cd Wi-Fi-Senhas
```

**3. Execute o aplicativo:**

```bash
python wifi_senhas.py
```

## Segurança e privacidade

O aplicativo permite visualizar informações de autenticação das redes Wi-Fi armazenadas no computador.

**Utilize exclusivamente no seu próprio computador ou em equipamentos para os quais você tenha autorização.**

- Não utilize o aplicativo para acessar redes sem autorização.
- Mantenha os arquivos exportados em local seguro.
- Evite compartilhar arquivos que contenham senhas de redes Wi-Fi.
- Utilize as permissões necessárias para realizar as operações de gerenciamento.

## Tecnologias utilizadas

- **Python 3:** linguagem de programação.
- **Tkinter:** desenvolvimento da interface gráfica.
- **Recursos nativos do sistema operacional:** gerenciamento das configurações de redes Wi-Fi no Windows.

## Contribuição

Contribuições são bem-vindas!

Caso encontre algum problema, tenha sugestões de melhorias ou queira contribuir com o desenvolvimento, fique à vontade para abrir uma [Issue](https://github.com/IvandeCoelho/Wi-Fi-Senhas/issues) ou enviar um Pull Request.

## Licença

Este projeto está licenciado sob a licença [MIT](LICENSE).

---

**Wi-Fi Senhas** — Suas redes Wi-Fi em um só lugar.
