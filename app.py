import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd

# --- Configuração da Página ---
# Mudei para "wide" para as 7 colunas caberem perfeitamente na tela
st.set_page_config(page_title="Validação de Produtos", page_icon="📦", layout="wide")

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
st.markdown("Digite o código para carregar os dados. Preencha a observação e clique em OK para salvar.")

# Criação das 7 colunas (os números dentro da lista representam a largura de cada coluna)
col1, col2, col3, col4, col5, col6, col7 = st.columns([1, 2.5, 1.5, 1.5, 1, 2, 1])

# 1. Coluna do Código (Onde o usuário digita)
with col1:
    codigo_input = st.text_input("Código")

# Lógica para buscar o produto assim que o código for digitado
produto = None
if codigo_input:
    try:
        codigo_int = int(codigo_input)
        produto = buscar_produto(codigo_int)
        if not produto:
            st.warning("Produto não encontrado.")
    except ValueError:
        st.error("Digite apenas números.")

# 2 a 5. Colunas preenchidas automaticamente pelo banco (bloqueadas para edição)
with col2:
    st.text_input("Descrição", value=produto['descricao'] if produto else "", disabled=True)
with col3:
    st.text_input("Cód. Barra", value=produto['codbarra'] if produto else "", disabled=True)
with col4:
    st.text_input("DUM 14", value=str(produto['coddum14']) if produto and produto['coddum14'] else "", disabled=True)
with col5:
    st.text_input("Qtde Emb", value=str(produto['qtdeemb']) if produto else "", disabled=True)

# 6. Coluna de Observação (Onde o usuário digita a alteração)
with col6:
    observacao = st.text_input("Observação")

# 7. Coluna do Botão OK
with col7:
    # Esse markdown empurra o botão um pouco para baixo, para alinhar com as caixas de texto
    st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
    btn_ok = st.button("OK", type="primary", use_container_width=True)

# Lógica do Botão OK
if btn_ok:
    if produto:
        try:
            # Montando a linha para o Sheets. 
            # Deixei um espaço em branco "" no meio para pular a coluna "QtdeDisplay" da sua planilha e não desalinhar as colunas.
            linha_planilha = [
                produto['cod'],
                produto['descricao'],
                produto['codbarra'],
                str(produto['coddum14']),
                str(produto['qtdeemb']),
                "", # Coluna QtdeDisplay (vazia)
                observacao,
                "OK" # Coluna Status
            ]
            salvar_no_sheets(linha_planilha)
            st.success(f"Registro do produto **{produto['cod']}** salvo na planilha com sucesso!")
        except Exception as e:
            st.error(f"Erro ao salvar na planilha: {e}")
    else:
        st.warning("Busque um produto válido primeiro antes de confirmar.")

st.divider()

# --- Exibição do Histórico da Planilha ---
st.subheader("📋 Registros Salvos (Google Sheets)")
try:
    dados_planilha = sheet.get_all_records()
    if dados_planilha:
        df = pd.DataFrame(dados_planilha)
        # Exibe o dataframe atualizado na tela
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhum registro encontrado na planilha ainda.")
except Exception as e:
    st.error(f"Não foi possível carregar o histórico da planilha. Detalhes: {e}")
