import requests
import pandas as pd
from io import StringIO
import time
import datetime
import matplotlib.pyplot as plt
import os
import logging # Módulo para log
from logging.handlers import RotatingFileHandler # Para limitar o tamanho do arquivo de log

# --- CONFIGURAÇÕES DE LOG ---
LOG_FILENAME = 'log_execucao_cotas.txt'
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO) # Define o nível mínimo de log a ser processado
handler = RotatingFileHandler(
    LOG_FILENAME, 
    maxBytes=5*1024*1024, # 5 MB
    backupCount=0,
    encoding='utf-8'
)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
handler.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(handler)

# ROTINA
# Definição das datas para a consulta (últimos 7 dias)
agora = datetime.datetime.now()
hoje = agora.date()
data_fim_consulta = (hoje + datetime.timedelta(days=1)).strftime('%d-%m-%Y') 
data_inicio_consulta = (hoje - datetime.timedelta(days=7)).strftime('%d-%m-%Y') 

# Definição do nome do arquivo de lista e leitura
nome_do_arquivo = 'lista.txt'


# cotas de referencia
nome_arquivo_referencia = 'cotas_referencia.txt'
cotas_ref = pd.DataFrame() # Inicializa como DataFrame vazio

try:
    # Lê o CSV, garantindo que a coluna Codigo é string e a define como índice
    cotas_ref = pd.read_csv(
        nome_arquivo_referencia,
        dtype={'Codigo': str} 
    ).set_index('Codigo')
except FileNotFoundError:
    logger.warning(f"Arquivo de referência '{nome_arquivo_referencia}' não encontrado. As linhas de alerta/inundação não serão plotadas.")
except Exception as e:
    logger.error(f"Erro ao carregar o arquivo de referência: {e}")


try:
    with open(nome_do_arquivo, 'r', encoding='utf-8') as arquivo:
        lista_estacoes = [
            linha.strip()
            for linha in arquivo
            if linha.strip() and not linha.startswith('#')
        ]
except FileNotFoundError:
    logger.error(f"ERRO: Arquivo '{nome_do_arquivo}' não encontrado.")
    exit()

if not lista_estacoes:
    logger.error("ERRO: A lista de estações está vazia após a leitura do arquivo.")
    exit()

# Cria o diretório para salvar os gráficos se ele não existir
diretorio_graficos = 'Graficos_Saida'
os.makedirs(diretorio_graficos, exist_ok=True)


# LOOP PRINCIPAL DE PROCESSAMENTO

for codigo in lista_estacoes:
    
    # INVENTÁRIO (Para obter o nome da estação)
    url_inventario = f'https://telemetriaws1.ana.gov.br/ServiceANA.asmx/HidroInventario?codEstDE={codigo}&codEstATE={codigo}&tpEst=&nmEst=&nmRio=&codSubBacia=&codBacia=&nmMunicipio=&nmEstado=&sgResp=&sgOper=&telemetrica='
    
    try:
        response_inventario = requests.get(url_inventario, timeout=30)
        xml_inventario = response_inventario.content.decode('utf-8')
        inventario = pd.read_xml(StringIO(xml_inventario), xpath='.//Table')
        
        if not inventario.empty:
            nome = inventario['Nome'].iloc[0]
        else:
            logger.warning(f"Estação {codigo}: Não encontrada no inventário da ANA.")
            
    except Exception as e:
        logger.error(f"Estação {codigo}: Erro ao consultar inventário da ANA. Detalhe: {e}")
        
        
    # DADOS
    url_dados = f'https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos?codEstacao={codigo}&dataInicio={data_inicio_consulta}&dataFim={data_fim_consulta}'
    
    try:
        response_dados = requests.get(url_dados, timeout=60)
        xml_dados = response_dados.content.decode('utf-8')
        df_cota_temp = pd.read_xml(StringIO(xml_dados), xpath=".//DadosHidrometereologicos")
        
        if df_cota_temp.empty:
            logger.warning(f"Estação {codigo}: Nenhum dado de cota encontrado no período de consulta.")
            continue
            
        
        df_cota_temp['DataHora'] = pd.to_datetime(df_cota_temp['DataHora'])
        
        df_cota = (df_cota_temp
                   .dropna(subset=['DataHora', 'Nivel'])
                   .rename(columns={'Nivel': 'Cota'})
                   .set_index('DataHora')
                   .sort_index(ascending=True)
                  )
        
        if df_cota.empty:
            logger.warning(f"Estação {codigo}: Nenhum dado válido de cota encontrado após limpeza.")
            continue
            
        # GRÁFICO
        
        ultimo_dado = df_cota['Cota'].iloc[-1]
        data_ultimo_dado = df_cota.index[-1].strftime('%d/%m/%y %H:%M')
        
        # Criação da figura e eixos
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(df_cota.index, df_cota['Cota'], linestyle='-', markersize=2, linewidth=1.5, color='blue', label='Nível do rio')

        if codigo in cotas_ref.index:
            ref_data = cotas_ref.loc[codigo]
            alerta = ref_data['Alerta']
            inundacao = ref_data['Inundacao']

            # Linha de Alerta (Laranja)
            ax.axhline(y=alerta, color='orange', linestyle='--', linewidth=1.5, label=f'Alerta ({alerta} cm)')

            # Linha de Inundação (Vermelho)
            ax.axhline(y=inundacao, color='red', linestyle='--', linewidth=1.5, label=f'Inundação ({inundacao} cm)')

            # Adiciona legenda para mostrar todas as linhas plotadas
            ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.3), ncol=3)


        # Configurando Títulos e Eixos
        ax.set_title(f'Estação {codigo}: {nome} - Cotas dos últimos 7 dias', fontsize=14)
        ax.set_xlabel('Data', fontsize=12)
        ax.set_ylabel('Cota (cm)', fontsize=12)
        ax.grid(True, linestyle='--', alpha=0.6)
        
        fig.autofmt_xdate(rotation=45)
        
        # Adicionando a Text Box com o último dado
        text_box = (f"Último Dado:\n"
                    f"Data: {data_ultimo_dado}\n"
                    f"Cota: {ultimo_dado:.0f} cm")
        
        props = dict(boxstyle='round', facecolor='wheat', alpha=0.5)
        ax.text(0.80, -0.25, text_box, transform=ax.transAxes, fontsize=10,
                verticalalignment='top', horizontalalignment='left', bbox=props)
                
        # Salvando o gráfico 
        nome_arquivo_grafico = os.path.join(diretorio_graficos, f'{codigo}.png')

        plt.tight_layout(rect=[0, 0.02, 1, 1])
        plt.savefig(nome_arquivo_grafico)
        plt.close(fig) 
        
    except Exception as e:
        logger.error(f"Estação {codigo}: ERRO CRÍTICO no processamento, plotagem ou consulta de dados. Detalhe: {e}")
        # Continua para a próxima estação

