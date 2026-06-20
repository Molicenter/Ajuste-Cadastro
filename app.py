import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, timezone, timedelta # <-- Nova importação para datas

# --- Configuração da Página ---
st.set_page_config(page_title="Validação de Produtos", page_icon="📦", layout="wide")

# --- Função de Data e Hora (Fuso de Brasília) ---
def obter_data_hora_atual():
    fuso_br = timezone(timedelta(hours=-3))
    return datetime.now(fuso_br).strftime("%d/%m/%Y %H:%M:%S")

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
    planilha = client.open("Ajuste_Cadastro")
    
    aba_gerente = planilha.worksheet("Gerente")
    aba_finalizado = planilha.worksheet("Finalizado")
    return aba_gerente, aba_finalizado

try:
    sheet_gerente, sheet_finalizado = init_gsheets()
except Exception as e:
    st.error(f"Erro ao conectar com as abas do Google Sheets: {e}")
    st.stop()

# --- Funções de Banco ---
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

# --- Interface do Usuário ---
st.title("📦 Validação de Produtos")

# =====================================================================
# BLOCO 1: SOLICITAÇÃO (GERENTE DO DEPÓSITO)
# =====================================================================
st.subheader("🧑‍💼 Solicitação do Gerente do Depósito")
st.markdown("Digite o código para carregar os dados. Preencha a observação e clique em 'Enviar para Ajuste'.")

col1, col2, col3, col4, col5, col6, col7 = st.columns([1, 2, 1.5, 1.5, 1, 2, 1.5])

with col1:
    codigo_input = st.text_input("Código", key="input_gerente_cod")

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
    observacao = st.text_input("Observação", key="input_gerente_obs")
with col7:
    st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
    btn_enviar = st.button("Enviar para Ajuste", type="primary", use_container_width=True)

if btn_enviar:
    if produto:
        try:
            data_solicitacao = obter_data_hora_atual() # <-- Pega a data e hora do envio
            
            linha_gerente = [
                produto['cod'],
                produto['descricao'],
                produto['codbarra'],
                str(produto['coddum14']),
                str(produto['qtdeemb']),
                "", 
                observacao,
                "Pendente",
                data_solicitacao # <-- Salva a data na nova coluna da aba Gerente
            ]
            sheet_gerente.append_row(linha_gerente)
            st.success(f"Solicitação do produto **{produto['cod']}** enviada em {data_solicitacao}!")
        except Exception as e:
            st.error(f"Erro ao salvar solicitação: {e}")
    else:
        st.warning("Busque um produto válido primeiro antes de solicitar.")

st.markdown("---")

# =====================================================================
# BLOCO 2: VALIDAÇÃO (RESPONSÁVEL PELO AJUSTE)
# =====================================================================
st.subheader("✅ Validação do Responsável pelo Ajuste")

try:
    dados_fila = sheet_gerente.get_all_values()
    
    pendentes = []
    for idx_linha, linha in enumerate(dados_fila[1:], start=2):
        if len(linha) >= 8 and linha[7] == 'Pendente':
            # Proteção caso a linha antiga não tenha a data ainda
            data_solic = linha[8] if len(linha) > 8 else "Data não registrada" 
            
            pendentes.append({
                'row_idx': idx_linha,
                'Cod': linha[0],
                'Descricao': linha[1],
                'CodBarra': linha[2],
                'CodDum14': linha[3],
                'QtdeEmb': linha[4],
                'QtdeDisplay': linha[5],
                'Observacao': linha[6],
                'DataSolicitacao': data_solic # <-- Puxa a data da planilha
            })

    if pendentes:
        st.info(f"Existem **{len(pendentes)}** solicitações aguardando ajuste.")
        
        opcoes = {p['row_idx']: f"{p['Cod']} - {p['Descricao']} (Pedida em: {p['DataSolicitacao']})" for p in pendentes}
        
        col_v1, col_v2, col_v3 = st.columns([2, 3, 3])
        
        with col_v1:
            selecionado_idx = st.selectbox("Selecione a Solicitação na Fila", options=list(opcoes.keys()), format_func=lambda x: opcoes[x])
            item_selecionado = next(p for p in pendentes if p['row_idx'] == selecionado_idx)
            
        with col_v2:
            # Exibe a observação e a data em que foi feita para o responsável ver
            info_gerente = f"({item_selecionado['DataSolicitacao']}) {item_selecionado['Observacao']}"
            st.text_input("Observação Solicitada (Gerente)", value=info_gerente, disabled=True)
            
        with col_v3:
            obs_responsavel = st.text_input("Sua Observação da Validação (Opcional)", key="obs_resp")
            
            st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
            col_v3_1, col_v3_2 = st.columns([2, 1])
            with col_v3_2:
                btn_ajuste_ok = st.button("Ajuste OK", type="primary", use_container_width=True)

        if btn_ajuste_ok:
            data_ajuste = obter_data_hora_atual() # <-- Pega a data e hora em que o responsável deu OK

            obs_final = f"Gerente: {item_selecionado['Observacao']}"
            if obs_responsavel:
                obs_final += f" | Resp: {obs_responsavel}"

            linha_final = [
                item_selecionado['Cod'],
                item_selecionado['Descricao'],
                item_selecionado['CodBarra'],
                item_selecionado['CodDum14'],
                item_selecionado['QtdeEmb'],
                item_selecionado['QtdeDisplay'],
                obs_final,
                "OK",
                item_selecionado['DataSolicitacao'], # <-- Repassa a data original
                data_ajuste                          # <-- Adiciona a data da finalização
            ]
            
            sheet_finalizado.append_row(linha_final)
            sheet_gerente.update_cell(selecionado_idx, 8, 'Concluído')
            
            st.success(f"Ajuste do produto {item_selecionado['Cod']} finalizado em {data_ajuste}!")
            st.rerun() 
            
    else:
        st.success("Nenhuma solicitação pendente no momento! Tudo em dia. 🎉")

except Exception as e:
    st.error(f"Erro ao processar a fila de validação: {e}")

st.divider()

# =====================================================================
# BLOCO 3: EXIBIÇÃO DO HISTÓRICO DA PLANILHA (ABA FINALIZADO)
# =====================================================================
st.subheader("📋 Registros Validados (Aba 'Finalizado')")
try:
    dados_planilha = sheet_finalizado.get_all_records()
    if dados_planilha:
        df = pd.DataFrame(dados_planilha)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhum registro finalizado encontrado ainda.")
except Exception as e:
    st.error(f"Não foi possível carregar o histórico finalizado. Detalhes: {e}")
