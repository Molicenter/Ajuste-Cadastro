import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor

# --- Configuração da Página ---
st.set_page_config(page_title="Validação de Produtos", page_icon="📦", layout="centered")

# --- Conexão com o Banco de Dados ---
# Utilizando st.cache_resource para não recriar a conexão a cada interação
@st.cache_resource
def init_connection():
    return psycopg2.connect(**st.secrets["postgres"])

try:
    conn = init_connection()
except Exception as e:
    st.error(f"Erro ao conectar com o banco de dados: {e}")
    st.stop()

# --- Funções de Banco de Dados ---
def buscar_produto(codigo):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # ATENÇÃO: Adapte o nome da tabela e colunas conforme seu banco de dados
        query = """
            SELECT descricao, cod_barra, cod_dum_14, qnd_bem
            FROM produtos
            WHERE codigo_interno = %s
        """
        cur.execute(query, (codigo,))
        return cur.fetchone()

def salvar_execucao(codigo, observacao):
    with conn.cursor() as cur:
        # ATENÇÃO: Adapte para a sua tabela. Aqui fazemos um UPDATE na linha do produto.
        # Se for gravar um histórico em outra tabela, mude para um comando INSERT.
        query = """
            UPDATE produtos
            SET execucao = 'OK', observacao = %s
            WHERE codigo_interno = %s
        """
        cur.execute(query, (observacao, codigo))
        conn.commit()

# --- Interface do Usuário ---
st.title("📦 Validação de Produtos")
st.markdown("Digite o código interno para puxar as informações do banco de dados.")

# Campo de Busca
codigo_input = st.text_input("Código Interno do Produto:")

if codigo_input:
    # Busca no banco assim que algo é digitado (e apertado Enter)
    produto = buscar_produto(codigo_input)

    if produto:
        st.success("Produto localizado!")

        # Exibindo os dados de forma bloqueada (somente leitura)
        col1, col2 = st.columns(2)
        with col1:
            st.text_input("Descrição", value=produto['descricao'], disabled=True)
            st.text_input("Cód. Barra", value=produto['cod_barra'], disabled=True)
        with col2:
            st.text_input("Cód. DUM 14", value=produto['cod_dum_14'], disabled=True)
            st.text_input("Qtde. Bem", value=produto['qnd_bem'], disabled=True)

        st.divider()

        # Área de Observação e Finalização
        st.subheader("Finalizar Processo")
        observacao = st.text_area("Observações / Mudanças (Opcional):", placeholder="Anexe qualquer mudança antes do OK...")

        # Botão em destaque para o OK
        if st.button("OK - Confirmar Execução", type="primary"):
            try:
                salvar_execucao(codigo_input, observacao)
                st.success(f"A execução do produto **{codigo_input}** foi finalizada e salva no banco!")
                st.balloons() # Um efeito visual bacana para dar feedback de sucesso
            except Exception as e:
                st.error(f"Erro ao salvar no banco: {e}")
                
    else:
        st.warning("Produto não encontrado. Verifique o código digitado.")
