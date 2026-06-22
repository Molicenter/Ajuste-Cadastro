import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor
from supabase import create_client, Client
import pandas as pd
import io
from datetime import datetime, timezone, timedelta
import requests 

# --- Configuração da Página ---
st.set_page_config(page_title="Validação de Produtos", page_icon="📦", layout="wide")

# --- Função de Data e Hora (Fuso de Brasília) ---
def obter_data_hora_atual():
    fuso_br = timezone(timedelta(hours=-3))
    return datetime.now(fuso_br).strftime("%d/%m/%Y %H:%M:%S")

# --- Função de Notificação via Telegram ---
def notificar_telegram(mensagem): # Parâmetro corrigido
    try:
        bot_token = st.secrets["telegram"]["bot_token"]
        chat_id = st.secrets["telegram"]["chat_id"]
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        
        payload = {
            "chat_id": chat_id,
            "text": mensagem, # Variável corrigida para casar com o parâmetro
            "parse_mode": "HTML"
        }
        requests.post(url, data=payload)
    except Exception as e:
        st.warning(f"Erro ao enviar notificação no Telegram: {e}")

# --- Conexão com o Banco de Dados ERP (PostgreSQL) ---
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
    st.error(f"Erro ao conectar com o banco de dados PostgreSQL ERP: {e}")
    st.stop()

# --- CONEXÃO SUPABASE ---
@st.cache_resource
def init_supabase():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

try:
    supabase: Client = init_supabase()
except Exception as e:
    st.error(f"Erro ao inicializar o Supabase: {e}")
    st.stop()


# --- Funções de Banco (ERP) ---
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

col1, col2, col3, col4, col5, col6, col7, col8 = st.columns([1, 1.8, 1.5, 1.5, 1, 1, 1.5, 1.2])

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
    qtde_display = st.text_input("Qtde Display", key="input_gerente_qtdedisplay")
with col7:
    observacao = st.text_input("Observação", key="input_gerente_obs")
with col8:
    st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
    btn_enviar = st.button("Enviar Ajuste", type="primary", use_container_width=True)

if btn_enviar:
    if produto:
        try:
            data_solicitacao = obter_data_hora_atual() 
            dados_insercao = {
                "cod": str(produto['cod']),
                "descricao": produto['descricao'],
                "codbarra": produto['codbarra'],
                "coddum14": str(produto['coddum14']) if produto['coddum14'] else "",
                "qtdeemb": str(produto['qtdeemb']),
                "qtdedisplay": qtde_display,
                "observacao_gerente": observacao,
                "status": "Pendente",
                "data_solicitacao": data_solicitacao
            }
            supabase.table("ajustes_cadastro").insert(dados_insercao).execute()
            st.success(f"Solicitação do produto **{produto['cod']}** enviada!")
            
            msg_telegram = (
                f"📦 <b>NOVA SOLICITAÇÃO</b>\n\n"
                f"<b>Produto:</b> {produto['cod']} - {produto['descricao']}\n"
                f"<b>Qtde Display:</b> {qtde_display}\n"
                f"<b>Observação:</b> {observacao}"
            )
            notificar_telegram(msg_telegram)
            st.rerun()
            
        except Exception as e:
            st.error(f"Erro ao salvar: {e}")
    else:
        st.warning("Busque um produto primeiro.")

st.markdown("---")

# =====================================================================
# BLOCO 2: VALIDAÇÃO (RESPONSÁVEL PELO AJUSTE)
# =====================================================================
st.subheader("✅ Validação do Responsável pelo Ajuste")

try:
    resposta_pendentes = supabase.table("ajustes_cadastro").select("*").eq("status", "Pendente").execute()
    pendentes = resposta_pendentes.data

    if pendentes:
        opcoes = {p['id']: f"{p['cod']} - {p['descricao']}" for p in pendentes}
        col_v1, col_v2, col_v3, col_v4, col_v5 = st.columns([2.5, 2.5, 1.5, 2.5, 1.2])
        
        with col_v1:
            selecionado_id = st.selectbox("Selecione a Solicitação", options=list(opcoes.keys()), format_func=lambda x: opcoes[x])
            item_selecionado = next(p for p in pendentes if p['id'] == selecionado_id)
        with col_v2:
            st.text_input("Obs Gerente", value=item_selecionado['observacao_gerente'] or "", disabled=True)
        with col_v3:
            st.text_input("Data Solic.", value=item_selecionado['data_solicitacao'] or "", disabled=True)
        with col_v4:
            obs_responsavel = st.text_input("Sua Observação", key="obs_resp")
        with col_v5:
            st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
            btn_ajuste_ok = st.button("Ajuste OK", type="primary", use_container_width=True)

        if btn_ajuste_ok:
            data_ajuste = obter_data_hora_atual()
            supabase.table("ajustes_cadastro").update({"status": "Concluído", "observacao_responsavel": obs_responsavel, "data_ajuste": data_ajuste}).eq("id", selecionado_id).execute()
            
            msg_ok = f"✅ <b>AJUSTE CONCLUÍDO</b>\n\n<b>Produto:</b> {item_selecionado['cod']} - {item_selecionado['descricao']}"
            notificar_telegram(msg_ok)
            st.rerun() 
            
    else:
        st.success("Tudo em dia! 🎉")
except Exception as e:
    st.error(f"Erro na fila: {e}")

st.divider()

# =====================================================================
# BLOCO 3: EXPORTAÇÃO (VERSÃO SEGURA)
# =====================================================================
st.subheader("📋 Histórico")
try:
    # Busca os dados
    resposta_historico = supabase.table("ajustes_cadastro").select("*").eq("status", "Concluído").order("id", desc=True).execute()
    historico = resposta_historico.data
    
    if historico and len(historico) > 0: 
        df = pd.DataFrame(historico)
        
        # Cria o Excel em memória
        buffer_hist = io.BytesIO()
        with pd.ExcelWriter(buffer_hist, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name="Historico")
        
        # Botão de download
        st.download_button(
            label="📊 Exportar Histórico para Excel",
            data=buffer_hist.getvalue(),
            file_name="historico_ajustes.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        # Exibe a tabela
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhum registro finalizado encontrado no histórico.")
        
except Exception as e:
    st.error(f"Erro ao carregar histórico: {e}")
