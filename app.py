import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, timezone, timedelta
import requests # <-- Importação necessária para o Telegram

# --- Configuração da Página ---
st.set_page_config(page_title="Validação de Produtos", page_icon="📦", layout="wide")

# --- Função de Data e Hora (Fuso de Brasília) ---
def obter_data_hora_atual():
    fuso_br = timezone(timedelta(hours=-3))
    return datetime.now(fuso_br).strftime("%d/%m/%Y %H:%M:%S")

# --- Função de Notificação via Telegram ---
def notificar_telegram(mensagem):
    try:
        bot_token = st.secrets["telegram"]["token"]
        chat_id = st.secrets["telegram"]["chat_id"]
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        
        payload = {
            "chat_id": chat_id,
            "text": mensagem,
            "parse_mode": "HTML"
        }
        requests.post(url, data=payload)
    except Exception as e:
        st.warning(f"Erro ao enviar notificação no Telegram: {e}")

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
            data_solicitacao = obter_data_hora_atual() 
            
            linha_gerente = [
                produto['cod'],
                produto['descricao'],
                produto['codbarra'],
                str(produto['coddum14']),
                str(produto['qtdeemb']),
                "", 
                observacao,
                "Pendente",
                data_solicitacao
            ]
            sheet_gerente.append_row(linha_gerente)
            st.success(f"Solicitação do produto **{produto['cod']}** enviada em {data_solicitacao}!")
            
            # --- Gatilho do Telegram: Solicitação Enviada ---
            msg_telegram = (
                f"📦 <b>NOVA SOLICITAÇÃO DE AJUSTE</b>\n\n"
                f"<b>Produto:</b> {produto['cod']} - {produto['descricao']}\n"
                f"<b>Observação:</b> {observacao}\n"
                f"<b>Enviado em:</b> {data_solicitacao}"
            )
            notificar_telegram(msg_telegram)
            
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
            data_solic = linha[8] if len(linha) > 8 else "Sem data" 
            
            pendentes.append({
                'row_idx': idx_linha,
                'Cod': linha[0],
                'Descricao': linha[1],
                'CodBarra': linha[2],
                'CodDum14': linha[3],
                'QtdeEmb': linha[4],
                'QtdeDisplay': linha[5],
                'Observacao': linha[6],
                'DataSolicitacao': data_solic 
            })

    if pendentes:
        st.info(f"Existem **{len(pendentes)}** solicitações aguardando ajuste.")
        
        opcoes = {p['row_idx']: f"{p['Cod']} - {p['Descricao']}" for p in pendentes}
        
        col_v1, col_v2, col_v3, col_v4, col_v5 = st.columns([2.5, 2.5, 1.5, 2.5, 1.2])
        
        with col_v1:
            selecionado_idx = st.selectbox("Selecione a Solicitação", options=list(opcoes.keys()), format_func=lambda x: opcoes[x])
            item_selecionado = next(p for p in pendentes if p['row_idx'] == selecionado_idx)
            
        with col_v2:
            st.text_input("Observação do Gerente", value=item_selecionado['Observacao'], disabled=True)
            
        with col_v3:
            st.text_input("Enviado em", value=item_selecionado['DataSolicitacao'], disabled=True)
            
        with col_v4:
            obs_responsavel = st.text_input("Sua Observação (Opcional)", key="obs_resp")
            
        with col_v5:
            st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
            btn_ajuste_ok = st.button("Ajuste OK", type="primary", use_container_width=True)

        if btn_ajuste_ok:
            data_ajuste = obter_data_hora_atual()

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
                item_selecionado['DataSolicitacao'],
                data_ajuste                          
            ]
            
            sheet_finalizado.append_row(linha_final)
            sheet_gerente.update_cell(selecionado_idx, 8, 'Concluído')
            
            st.success(f"Ajuste do produto {item_selecionado['Cod']} finalizado em {data_ajuste}!")
            
            # --- Gatilho do Telegram: Ajuste Finalizado ---
            msg_ok = (
                f"✅ <b>AJUSTE CONCLUÍDO</b>\n\n"
                f"<b>Produto:</b> {item_selecionado['Cod']} - {item_selecionado['Descricao']}\n"
                f"<b>Finalizado em:</b> {data_ajuste}"
            )
            notificar_telegram(msg_ok)
            
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
    dados_planilha = sheet_finalizado.get_all_values()
    
    if len(dados_planilha) > 1: 
        cabecalhos = dados_planilha[0]
        cabecalhos_seguros = [col if col.strip() != "" else f"Coluna_Sem_Nome_{i}" for i, col in enumerate(cabecalhos)]
        
        df = pd.DataFrame(dados_planilha[1:], columns=cabecalhos_seguros)
        st.dataframe(df, use_container_width=True, hide_index=True)
        
    elif len(dados_planilha) == 1:
        st.info("Nenhum registro finalizado encontrado ainda.")
    else:
        st.warning("A aba 'Finalizado' está vazia. Adicione os cabeçalhos na linha 1.")
        
except Exception as e:
    st.error(f"Não foi possível carregar o histórico finalizado. Detalhes: {e}")
