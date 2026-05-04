from flask import Flask, render_template, request, redirect, url_for, session, flash
from supabase import create_client, Client
import os


app = Flask(__name__)
app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY", "chave-padrao-muito-segura")

# O Render preencherá estas variáveis automaticamente se você configurar no painel
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


@app.route('/')
def index():
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        try:
            # Autentica no Supabase
            response = supabase.auth.sign_in_with_password(
                {"email": email, "password": password})

            # Busca o grupo/role nos metadados do usuário
            # Nota: Você deve configurar o 'role' no user_metadata ao criar o usuário
            user_role = response.user.user_metadata.get('role', 'paciente')

            # Salva na sessão
            session['user'] = response.user.id
            session['role'] = user_role

            # Redirecionamento baseado no grupo
            if user_role == 'admin':
                return redirect(url_for('admin_dashboard'))
            elif user_role == 'nutricionista':
                return redirect(url_for('nutri_dashboard'))
            else:
                return redirect(url_for('paciente_dashboard'))

        except Exception as e:
            flash("Erro ao logar: Verifique suas credenciais.")
            return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/dashboard/admin')
def admin_dashboard():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    return render_template('admin.html')


@app.route('/dashboard/nutricionista')
def nutri_dashboard():
    if session.get('role') != 'nutricionista':
        return redirect(url_for('login'))
    return render_template('nutricionista.html')


@app.route('/dashboard/paciente')
def paciente_dashboard():
    if session.get('role') != 'paciente':
        return redirect(url_for('login'))

    user_id = session.get('user')

    # Busca o plano ativo do paciente
    plano = supabase.table('planos_alimentares') \
        .select('*') \
        .eq('paciente_id', user_id) \
        .eq('ativo', True) \
        .maybe_single() \
        .execute()

    refeicoes = []
    if plano.data:
        # Busca as refeições daquele plano
        res_refeicoes = supabase.table('refeicoes') \
            .select('*') \
            .eq('plano_id', plano.data['id']) \
            .order('horario') \
            .execute()
        refeicoes = res_refeicoes.data

    return render_template('paciente.html', plano=plano.data, refeicoes=refeicoes)


@app.route('/salvar_plano', methods=['POST'])
def salvar_plano():
    if session.get('role') != 'nutricionista':
        return redirect(url_for('login'))

    # 1. Identificar Paciente
    email = request.form.get('paciente_email')
    res_paciente = supabase.table('perfis').select(
        'id').eq('email', email).single().execute()

    if not res_paciente.data:
        return "Erro: Paciente não encontrado", 404

    pac_id = res_paciente.data['id']

    # 2. Criar Plano Alimentar
    dados_plano = {
        "paciente_id": pac_id,
        "nutri_id": session.get('user'),
        "titulo": request.form.get('titulo_plano')
    }
    novo_plano = supabase.table(
        'planos_alimentares').insert(dados_plano).execute()
    plano_id = novo_plano.data[0]['id']

    # 3. LOOP DE SALVAMENTO DAS REFEIÇÕES
    # Filtramos as chaves do formulário que começam com 'nome_'
    indices = [k.split('_')[1]
               for k in request.form.keys() if k.startswith('nome_')]

    for i in indices:
        refeicao = {
            "plano_id": plano_id,
            "horario": request.form.get(f'hora_{i}'),
            "nome_refeicao": request.form.get(f'nome_{i}'),
            "alimentos": request.form.get(f'desc_{i}'),
            "macros_estimados": {
                "carb": request.form.get(f'carb_{i}', 0),
                "prot": request.form.get(f'prot_{i}', 0),
                "gord": request.form.get(f'gord_{i}', 0)
            },
            "ordem": i
        }
        supabase.table('refeicoes').insert(refeicao).execute()

    # 4. Criar Notificação para o Paciente
    supabase.table('notificacoes').insert({
        "paciente_id": pac_id,
        "mensagem": f"Um novo plano '{dados_plano['titulo']}' foi publicado!"
    }).execute()

    return redirect(url_for('nutri_dashboard'))


@app.route('/meus-exames')
def listar_exames():
    if session.get('role') != 'paciente':
        return redirect(url_for('login'))

    user_id = session.get('user')

    # 1. Busca o e-mail do paciente para localizar a pasta no Storage
    user_data = supabase.table('perfis').select(
        'email').eq('id', user_id).single().execute()
    email = user_data.data['email']

    try:
        # 2. Lista os arquivos dentro da pasta do e-mail no bucket 'exames'
        caminho_pasta = f'exames/{email}'
        arquivos = supabase.storage.from_('exames').list(caminho_pasta)

        lista_exames = []
        for arq in arquivos:
            # 3. Cria uma URL pública ou assinada válida por 60 minutos
            res_url = supabase.storage.from_('exames').create_signed_url(
                f"{caminho_pasta}/{arq['name']}", 3600)

            lista_exames.append({
                "nome": arq['name'],
                "url": res_url['signedURL'],
                "data": arq['created_at']
            })

        return render_template('exames.html', exames=lista_exames)

    except Exception as e:
        print(f"Erro ao buscar exames: {e}")
        return render_template('exames.html', exames=[], erro="Nenhum exame encontrado.")


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(debug=True)
