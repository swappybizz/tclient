import streamlit as st
import os
from pymongo import MongoClient
from bson.binary import Binary
from openai import OpenAI
import fitz  # PyMuPDF
import docx
import json
from datetime import datetime

st.set_page_config(page_title="Client Checklist Viewer", page_icon=":clipboard:")

if "messages" not in st.session_state:
    st.session_state.messages = []


MONGO_URI = st.secrets["mongo_uri"]
client = MongoClient(MONGO_URI)
db = client["Terje_checklist"]
collection = db["checklist"]
client_knowledge = db["client_knowledge"]
client_submissions = db["client_submissions"]

st.title("Smart Checklist Bot")

# Client input
client_id = st.text_input("Enter your Client ID:")

if client_id:
    # Find checklists assigned to the client
    assigned_checklists = list(
        collection.find({"assigned_clients": client_id}).sort("upload_date", -1)
    )

    if assigned_checklists:
        st.sidebar.title("Assigned Checklists")
        checklist_titles = [checklist["filename"] for checklist in assigned_checklists]
        selected_checklist = st.sidebar.radio("Select a checklist", checklist_titles)

        selected_content = None
        for checklist in assigned_checklists:
            if checklist["filename"] == selected_checklist:
                selected_content = checklist["content"]
                break

        if selected_content:
            with st.expander("Checklist Content", expanded=False):
                st.text_area(
                    "File Content", selected_content, height=500, disabled=True
                )
    else:
        st.warning("No checklists assigned to this client ID.")
else:
    st.text("Please enter your client ID to view assigned checklists.")

# Upload client knowledge documents
st.sidebar.markdown("---")
st.sidebar.title("Upload Knowledge Documents")
uploaded_file = st.sidebar.file_uploader(
    "Upload a document (PDF or DOC)", type=["pdf", "txt", "docx"]
)

if uploaded_file and client_id:
    file_name = uploaded_file.name

    # Check for duplicate filenames for the same client
    if client_knowledge.find_one({"client_id": client_id, "filename": file_name}):
        st.sidebar.warning(
            "A file with this name already exists for this client. Please rename your file and try again."
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
        st.sidebar.success(f"File '{file_name}' uploaded successfully!")


# Display client knowledge documents
if client_id:
    client_docs = list(client_knowledge.find({"client_id": client_id}))

    if client_docs:
        st.sidebar.title("Client Knowledgebase")
        for doc in client_docs:
            with st.sidebar:
                with st.container(border=True):
                    st.markdown(f"**{doc['filename']}**")
    else:
        st.sidebar.info("No knowledge documents uploaded for this client ID.")


for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
if prompt := st.chat_input("Hi, lets start solving!"):
    with st.chat_message("user"):
        st.markdown(prompt)
        # Add user message to chat history
        st.session_state.messages.append({"role": "user", "content": prompt})
    client = OpenAI(api_key=st.secrets["openai_api_key"])
    checklist_content = selected_content
    prompty = f"""
        You are having a conversation with a client who has to fill a checklist for a task.
        You are assisting the client to fill the checklist.
        You have been provided the checklist and the conversation history and the user's latest message.
        The client may also have uploaded documents that may be helpful in filling the checklist, If they have, they would be provided to you.
        This set of documents may or may not be sufficient to fill the checklist.
        But its always good to have more details irrespective of the documents.
        You will respond to the user in such a way that the connversation leads to filling the checklist.
        You will only respond witht the reply to the user, add no other information.
        Your reply should be in coherence with the conversation history and the checklist.
        ###
        Checklist:
        {checklist_content}

        Supporting Documents:
        {client_docs}
        
        
        conversation history:
        {st.session_state["messages"]}
        user's latest message:
        {prompt}
        ###
        Your reply should be a assertion / command / comment / statement followed by a question, or simply a question that will carry the conversation forward.
        You must also explain the significance of the question and how much checklist has been filled in approx %.
        You will only respond with the reply to the user, add no other information.
        """
    completion = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": "You are a polite and helpful data entry clerk.",
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
    if st.button("Submit for Audit"):
        submi_prompt = f"""
        You have been provided with a checklist and a conversation between an agent and the user who had to fill the checklist.
        You will use the conversation history and the checklist to fill the checklist.
        You will be accurate in filling the checklist.
        You will not fill the checklist with any information that is not present in the conversation history.
        You will return a text response with the filled checklist.
        You will keep the text of the checklist same as the original checklist.
        You will also return comments about user's conversation with respect to the filling experience.
        Here is the conversation history and the checklist.
        ###
        Checklist:
        {selected_content}
        
        conversation history:
        {st.session_state["messages"]}
        ###
        
        Your resoponse must be in following format:
        ***
        Checklist:
        Item 1:
        Response 1:
        Item 2:
        Response 2:
        .... so on
        
        Comments:
        [Your comments here.]
        ***
            
        """
        client = OpenAI(api_key=st.secrets["openai_api_key"])
        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "user", "content": "You are a survey analyst and reporter."},
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
