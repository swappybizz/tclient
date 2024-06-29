import streamlit as st
from pymongo import MongoClient
from openai import OpenAI
import fitz  # PyMuPDF
import docx
from datetime import datetime

st.set_page_config(page_title="Klient Sjekkliste Visning", page_icon=":clipboard:")

if "messages" not in st.session_state:
    st.session_state.messages = []

MONGO_URI = st.secrets["mongo_uri"]
client = MongoClient(MONGO_URI)
db = client["Terje_checklist"]
collection = db["checklist"]
client_knowledge = db["client_knowledge"]
client_submissions = db["client_submissions"]

st.title("Smart Sjekkliste Bot")

# Client input
client_id = st.text_input("Skriv inn din Klient ID:")

if client_id:
    # Find checklists assigned to the client
    assigned_checklists = list(
        collection.find({"assigned_clients": client_id}).sort("upload_date", -1)
    )

    if assigned_checklists:
        st.sidebar.title("Tildelte Sjekklister")
        checklist_titles = [checklist["filename"] for checklist in assigned_checklists]
        selected_checklist = st.sidebar.radio("Velg en sjekkliste", checklist_titles)

        selected_content = None
        for checklist in assigned_checklists:
            if checklist["filename"] == selected_checklist:
                selected_content = checklist["content"]
                break

        if selected_content:
            with st.expander("Sjekkliste Innhold", expanded=False):
                st.text_area(
                    "Fil Innhold", selected_content, height=500, disabled=True
                )
    else:
        st.warning("Ingen sjekklister tildelt denne klient IDen.")
else:
    st.text("Vennligst skriv inn din klient ID for å se tildelte sjekklister.")

# Upload client knowledge documents
st.sidebar.markdown("---")
st.sidebar.title("Last opp Kunnskapsdokumenter")
uploaded_file = st.sidebar.file_uploader(
    "Last opp et dokument (PDF eller DOC)", type=["pdf", "txt", "docx"]
)

if uploaded_file and client_id:
    file_name = uploaded_file.name

    # Check for duplicate filenames for the same client
    if client_knowledge.find_one({"client_id": client_id, "filename": file_name}):
        st.sidebar.warning(
            "En fil med dette navnet finnes allerede for denne klienten. Vennligst gi filen et annet navn og prøv igjen."
        )
    else:
        file_content = uploaded_file.read()
        if file_name.endswith(".pdf"):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            content = ""
            for page in doc:
                content += page.getText()
        elif file_name.endswith(".docx"):
            doc = docx.Document(uploaded_file)
            content = ""
            for paragraph in doc.paragraphs:
                content += paragraph.text
        else:
            content = file_content.decode("utf-8")

        client_knowledge.insert_one(
            {"client_id": client_id, "filename": file_name, "content": content}
        )
        st.sidebar.success(f"Fil '{file_name}' lastet opp med suksess!")

# Display client knowledge documents
if client_id:
    client_docs = list(client_knowledge.find({"client_id": client_id}))

    if client_docs:
        st.sidebar.title("Klient Kunnskapsbase")
        for doc in client_docs:
            with st.sidebar:
                with st.container(border=True):
                    st.markdown(f"**{doc['filename']}**")
    else:
        st.sidebar.info("Ingen kunnskapsdokumenter lastet opp for denne klient IDen.")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
if prompt := st.chat_input("Hei, la oss starte med å løse!"):
    with st.chat_message("user"):
        st.markdown(prompt)
        # Add user message to chat history
        st.session_state.messages.append({"role": "user", "content": prompt})
    client = OpenAI(api_key=st.secrets["openai_api_key"])
    checklist_content = selected_content
    prompty = f"""
        Du har en samtale med en klient som må fylle ut en sjekkliste for en oppgave.
        Du hjelper klienten med å fylle ut sjekklisten.
        Du har fått sjekklisten og samtalehistorikken og brukerens siste melding.
        Klienten kan også ha lastet opp dokumenter som kan være nyttige for å fylle ut sjekklisten. Hvis de har gjort det, vil de bli gitt til deg.
        Dette settet med dokumenter kan eller kan ikke være tilstrekkelig for å fylle ut sjekklisten.
        Men det er alltid bra å ha flere detaljer uavhengig av dokumentene.
        Du vil svare brukeren på en slik måte at samtalen fører til at sjekklisten blir fylt ut.
        Du vil bare svare med svaret til brukeren, legg ikke til annen informasjon.
        Svaret ditt skal være i samsvar med samtalehistorikken og sjekklisten.
        ###
        Sjekkliste:
        {checklist_content}

        Støttende Dokumenter:
        {client_docs}
        
        samtalehistorikk:
        {st.session_state["messages"]}
        brukerens siste melding:
        {prompt}
        ###
        Svaret ditt skal være en påstand / kommando / kommentar / uttalelse etterfulgt av et spørsmål, eller bare et spørsmål som vil føre samtalen videre.
        Du må også forklare betydningen av spørsmålet og hvor mye av sjekklisten som er fylt ut i prosent.
        Du vil bare svare med svaret til brukeren, legg ikke til annen informasjon.
        """
    completion = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": "Du er en høflig og hjelpsom dataregistreringsmedarbeider.",
            },
            {"role": "user", "content": prompty},
        ],
    )
    response = completion.choices[0].message.content
    print(response)
    st.session_state.messages.append({"role": "ai", "content": response})
    st.rerun()

with st.sidebar:
    st.divider()
    if st.button("Send inn for Revisjon"):
        submi_prompt = f"""
        Du har fått en sjekkliste og en samtale mellom en agent og brukeren som måtte fylle ut sjekklisten.
        Du vil bruke samtalehistorikken og sjekklisten for å fylle ut sjekklisten.
        Du vil være nøyaktig når du fyller ut sjekklisten.
        Du vil ikke fylle ut sjekklisten med informasjon som ikke finnes i samtalehistorikken.
        Du vil returnere et tekstsvar med den utfylte sjekklisten.
        Du vil holde teksten til sjekklisten den samme som den originale sjekklisten.
        Du vil også returnere kommentarer om brukerens samtale med hensyn til utfyllingsopplevelsen.
        Her er samtalehistorikken og sjekklisten.
        ###
        Sjekkliste:
        {selected_content}
        
        samtalehistorikk:
        {st.session_state["messages"]}
        ###
        
        Svaret ditt må være i følgende format:
        ***
        Sjekkliste:
        Punkt 1:
        Svar 1:
        Punkt 2:
        Svar 2:
        .... så videre
        
        Kommentarer:
        [Dine kommentarer her.]
        ***
        """
        client = OpenAI(api_key=st.secrets["openai_api_key"])
        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "user", "content": "Du er en undersøkelsesanalytiker og reporter."},
                {"role": "user", "content": submi_prompt},
            ],
        )
        response = completion.choices[0].message.content
        # add to client_submissions with current date and time and client_id
        client_submissions.insert_one(
            {
                "client_id": client_id,
                "submission": completion.choices[0].message.content,
                "current_date": datetime.now(),
            }
        )
        print(response)
