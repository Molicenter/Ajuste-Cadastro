import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd

# --- Configuração da Página ---
st.set_page_config(page_title="Validação de Produtos", page_icon="📦", layout="wide")

# --- Variáveis de Estado (Session State) ---
# Necessário para controlar o fluxo de 2 etapas (Gerente -> Responsável)
if 'aguardando_validacao' not in st.session_state:
    st.session_state.aguardando_validacao = False
if 'produto_atual' not in st.session_state:
    st.session_state.produto_atual = None
if 'obs_gerente' not in st.session_state:
    st.session_state.obs_gerente = ""

# --- Conexão com o Banco de Dados (PostgreSQL) ---
@st.cache_resource
def init_postgres():
    db_secrets = st.secrets["connections"]["banco_erp"]
    return psycopg2.connect(
        host=db_secrets["host"],
        port=db_secrets["port"], 
        dbname=db_secrets["database"],
        user=db_secrets["username"],
        password=db_secrets["password"]
    )

try:
    conn_pg = init_postgres()
except Exception as e:
    st.error(f"Erro ao conectar com o banco de dados PostgreSQL: {e}")
    st.stop()

# --- Conexão com o Google Sheets ---
@st.cache_resource
def init_gsheets():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    credentials = Credentials.from_service_account_info(
        st.secrets["connections"]["gsheets"],
        scopes=scopes
    )
    client = gspread.authorize(credentials)
    return client.open("Ajuste_Cadastro").sheet1

try:
    sheet = init_gsheets()
except Exception as e:
    st.error(f"Erro ao conectar com o Google Sheets: {e}")
    st.stop()

# --- Funções de Banco e Planilha ---
def buscar_produto(codigo):
    with conn_pg.cursor(cursor_factory=RealDictCursor) as cur:
        query = """
            SELECT distinct cadp_codigo as cod,
                   cadp_descricao as descricao,
                   cadp_codigobarra as codbarra,
                   cadp_dum14 as coddum14,
                   cast(cade_qemb as decimal (18,0)) AS qtdeemb
            FROM cadprod
            INNER JOIN cadprodemp ON (cadp_codigo = cade_codigo)
            WHERE cadp_codigo = %s
            ORDER BY 1
        """
        cur.execute(query, (codigo,))
        return cur.fetchone()

def salvar_no_sheets(dados):
    sheet.append_row(dados)

# --- Interface do Usuário ---
st.title("📦 Validação de Produtos")

# =====================================================================
# BLOCO 1: SOLICITAÇÃO (GERENTE DO DEPÓSITO)
# =====================================================================
st.subheader("🧑‍💼 Solicitação do Gerente do Depósito")
st.markdown("Digite o código para carregar os dados. Preencha a observação e clique em 'Enviar para Ajuste'.")

# Ajustei levemente a largura da última coluna para caber o novo botão
col1, col2, col3, col4, col5, col6, col7 = st.columns([1, 2, 1.5, 1.5, 1, 2, 1.5])

with col1:
    codigo_input = st.text_input("Código")

produto = None
if codigo_input:
    try:
        codigo_int = int(codigo_input)
        produto = buscar_produto(codigo_int)
        if not produto:
            st.warning("Produto não encontrado.")
    except ValueError:
        st.error("Digite apenas números.")

with col2:
    st.text_input("Descrição", value=produto['descricao'] if produto else "", disabled=True)
with col3:
    st.text_input("Cód. Barra", value=produto['codbarra'] if produto else "", disabled=True)
with col4:
    st.text_input("DUM 14", value=str(produto['coddum14']) if produto and produto['coddum14'] else "", disabled=True)
with col5:
    st.text_input("Qtde Emb", value=str(produto['qtdeemb']) if produto else "", disabled=True)
with col6:
    observacao = st.text_input("Observação")
with col7:
    st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
    # Botão alterado
    btn_enviar = st.button("Enviar para Ajuste", type="primary", use_container_width=True)

# Lógica do botão do Gerente
if btn_enviar:
    if produto:
        # Ao invés de salvar, ativamos o bloco 2 guardando as informações na sessão
        st.session_state.aguardando_validacao = True
        st.session_state.produto_atual = produto
        st.session_state.obs_gerente = observacao
    else:
        st.warning("Busque um produto válido primeiro antes de solicitar.")


# =====================================================================
# BLOCO 2: VALIDAÇÃO (RESPONSÁVEL PELO AJUSTE)
# =====================================================================
if st.session_state.aguardando_validacao:
    st.markdown("---")
    st.subheader("✅ Validação do Responsável pelo Ajuste")
    
    # Exibe um resumo do que está sendo validado para evitar erros
    p_atual = st.session_state.produto_atual
    st.info(f"**Avaliando produto:** {p_atual['cod']} - {p_atual['descricao']} | **Obs Gerente:** {st.session_state.obs_gerente}")
    
    col_v1, col_v2 = st.columns([5, 1.5])
    
    with col_v1:
        obs_responsavel = st.text_input("Observação da Validação (Opcional)")
    with col_v2:
        st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
        btn_ajuste_ok = st.button("Ajuste OK", type="primary", use_container_width=True)

    # Lógica do botão do Responsável (AQUI SALVA NO SHEETS)
    if btn_ajuste_ok:
        try:
            # Mescla as duas observações para manter o histórico claro na planilha
            obs_final = f"Gerente: {st.session_state.obs_gerente}"
            if obs_responsavel:
                obs_final += f" | Resp: {obs_responsavel}"

            linha_planilha = [
                p_atual['cod'],
                p_atual['descricao'],
                p_atual['codbarra'],
                str(p_atual['coddum14']),
                str(p_atual['qtdeemb']),
                "", # Coluna QtdeDisplay (vazia)
                obs_final,
                "OK" # Coluna Status
            ]
            salvar_no_sheets(linha_planilha)
            st.success(f"Ajuste do produto **{p_atual['cod']}** validado e enviado para a planilha com sucesso!")
            
            # Reseta o estado para esconder o bloco 2 e liberar para a próxima operação
            st.session_state.aguardando_validacao = False
            st.session_state.produto_atual = None
            st.session_state.obs_gerente = ""
            
        except Exception as e:
            st.error(f"Erro ao salvar na planilha: {e}")

st.divider()

# =====================================================================
# BLOCO 3: EXIBIÇÃO DO HISTÓRICO DA PLANILHA
# =====================================================================
st.subheader("📋 Registros Salvos (Google Sheets)")
try:
    dados_planilha = sheet.get_all_records()
    if dados_planilha:
        df = pd.DataFrame(dados_planilha)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhum registro encontrado na planilha ainda.")
except Exception as e:
    st.error(f"Não foi possível carregar o histórico da planilha. Detalhes: {e}")
