import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd

# --- Configuração da Página ---
st.set_page_config(page_title="Validação de Produtos", page_icon="📦", layout="centered")

# --- Conexão com o Banco de Dados (PostgreSQL) ---
@st.cache_resource
def init_postgres():
    # Acessando o bloco exato que você criou nos Secrets
    db_secrets = st.secrets["connections"]["banco_erp"]
    
    return psycopg2.connect(
        host=db_secrets["host"],
        port=db_secrets["port"], 
        dbname=db_secrets["database"], # Mapeando o seu 'database'
        user=db_secrets["username"],   # Mapeando o seu 'username'
        password=db_secrets["password"]
    )

# --- Conexão com o Google Sheets ---
@st.cache_resource
def init_gsheets():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    # Puxando as credenciais do Google do st.secrets
    credentials = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=scopes
    )
    client = gspread.authorize(credentials)
    # Abre a planilha pelo nome exato
    return client.open("Ajuste_Cadastro").sheet1

try:
    sheet = init_gsheets()
except Exception as e:
    st.error(f"Erro ao conectar com o Google Sheets: {e}")
    st.stop()

# --- Funções ---
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
        # Passando o código digitado como parâmetro para o %s
        cur.execute(query, (codigo,))
        return cur.fetchone()

def salvar_no_sheets(dados):
    # dados é uma lista na exata ordem das colunas da planilha
    sheet.append_row(dados)

# --- Interface do Usuário ---
st.title("📦 Validação de Produtos")

# Campo de Busca
codigo_input = st.text_input("Código do Produto (Cod):")

if codigo_input:
    # Como o cod_input vem como string do text_input, tentamos converter para int para a query
    try:
        codigo_int = int(codigo_input)
        produto = buscar_produto(codigo_int)
    except ValueError:
        st.warning("Por favor, digite um código numérico válido.")
        produto = None

    if produto:
        st.success("Produto localizado no banco de dados!")

        # Exibindo os dados do Postgres de forma bloqueada
        col1, col2 = st.columns(2)
        with col1:
            st.text_input("Descrição", value=produto['descricao'], disabled=True)
            st.text_input("Cód. Barra", value=produto['codbarra'], disabled=True)
        with col2:
            st.text_input("Cód. DUM 14", value=str(produto['coddum14']), disabled=True)
            st.text_input("Qtde. Emb", value=str(produto['qtdeemb']), disabled=True)

        st.divider()

        # Área de Inputs Extras e Finalização
        st.subheader("Finalizar Processo")
        
        # Novo campo para Qtde Display que tem na planilha
        qtde_display = st.text_input("Qtde Display:") 
        observacao = st.text_area("Observações (Opcional):")

        if st.button("OK - Confirmar Execução", type="primary"):
            try:
                # Montando a linha exatamente na ordem da planilha:
                # Cod | Descricao | CodBarra | CodDum14 | QtdeEmb | QtdeDisplay | Observacao | Status
                linha_planilha = [
                    produto['cod'],
                    produto['descricao'],
                    produto['codbarra'],
                    str(produto['coddum14']),
                    str(produto['qtdeemb']),
                    qtde_display,
                    observacao,
                    "OK"
                ]
                
                salvar_no_sheets(linha_planilha)
                st.success(f"A execução do produto **{produto['cod']}** foi salva na planilha com sucesso!")
                st.balloons()
            except Exception as e:
                st.error(f"Erro ao salvar na planilha: {e}")
                
    else:
        if codigo_input.isnumeric():
            st.warning("Produto não encontrado. Verifique o código digitado.")

st.divider()

# --- Exibição do Histórico da Planilha ---
st.subheader("📋 Registros Salvos (OK)")
try:
    # Puxa todos os dados da planilha
    dados_planilha = sheet.get_all_records()
    if dados_planilha:
        df = pd.DataFrame(dados_planilha)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhum registro encontrado na planilha ainda.")
except Exception as e:
    st.error("Não foi possível carregar o histórico da planilha.")
