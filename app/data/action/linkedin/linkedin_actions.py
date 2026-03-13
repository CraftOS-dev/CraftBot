from agent_core import action


@action(
    name="get_linkedin_profile",
    description="Get the authenticated user's LinkedIn profile.",
    action_sets=["linkedin"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_linkedin_profile(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        result = client.get_user_profile()
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="create_linkedin_post",
    description="Create a text post on LinkedIn.",
    action_sets=["linkedin"],
    input_schema={
        "text": {"type": "string", "description": "Post text (max 3000 chars).", "example": "Excited to share..."},
        "visibility": {"type": "string", "description": "Visibility: PUBLIC, CONNECTIONS, or LOGGED_IN.", "example": "PUBLIC"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def create_linkedin_post(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        cred = client._load()
        person_urn = f"urn:li:person:{cred.linkedin_id}" if cred.linkedin_id else f"urn:li:person:{cred.user_id}"
        result = client.create_text_post(
            person_urn, input_data["text"], visibility=input_data.get("visibility", "PUBLIC")
        )
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="search_linkedin_jobs",
    description="Search for job postings on LinkedIn.",
    action_sets=["linkedin"],
    input_schema={
        "keywords": {"type": "string", "description": "Job search keywords.", "example": "software engineer"},
        "location": {"type": "string", "description": "Optional location filter.", "example": ""},
        "count": {"type": "integer", "description": "Number of results.", "example": 25},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def search_linkedin_jobs(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        result = client.search_jobs(
            input_data["keywords"],
            location=input_data.get("location"),
            count=input_data.get("count", 25),
        )
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="get_linkedin_connections",
    description="Get the authenticated user's LinkedIn connections.",
    action_sets=["linkedin"],
    input_schema={
        "count": {"type": "integer", "description": "Number of connections to return.", "example": 50},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_linkedin_connections(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        result = client.get_connections(count=input_data.get("count", 50))
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="send_linkedin_message",
    description="Send a message to LinkedIn users.",
    action_sets=["linkedin"],
    input_schema={
        "recipient_urns": {"type": "array", "description": "List of recipient URNs (urn:li:person:xxx).", "example": []},
        "subject": {"type": "string", "description": "Message subject.", "example": "Hello"},
        "body": {"type": "string", "description": "Message body.", "example": "Hi, I wanted to connect..."},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def send_linkedin_message(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        cred = client._load()
        person_urn = f"urn:li:person:{cred.linkedin_id}" if cred.linkedin_id else f"urn:li:person:{cred.user_id}"
        result = client.send_message_to_recipients(
            person_urn, input_data["recipient_urns"], input_data["subject"], input_data["body"]
        )
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="delete_linkedin_post",
    description="Delete a LinkedIn post.",
    action_sets=["linkedin"],
    input_schema={"post_urn": {"type": "string", "description": "Post URN.", "example": "urn:li:share:123"}},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def delete_linkedin_post(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        result = client.delete_post(input_data["post_urn"])
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="get_linkedin_organizations",
    description="Get user's organizations.",
    action_sets=["linkedin"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_linkedin_organizations(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        result = client.get_my_organizations()
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="get_linkedin_organization_info",
    description="Get organization info.",
    action_sets=["linkedin"],
    input_schema={"organization_id": {"type": "string", "description": "Org ID.", "example": "123"}},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_linkedin_organization_info(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        result = client.get_organization(input_data["organization_id"])
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="get_linkedin_organization_analytics",
    description="Get organization analytics.",
    action_sets=["linkedin"],
    input_schema={"organization_urn": {"type": "string", "description": "Org URN.", "example": "urn:li:organization:123"}},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_linkedin_organization_analytics(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        result = client.get_organization_analytics(input_data["organization_urn"])
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="get_linkedin_job_details",
    description="Get job details.",
    action_sets=["linkedin"],
    input_schema={"job_id": {"type": "string", "description": "Job ID.", "example": "123"}},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_linkedin_job_details(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        result = client.get_job_details(input_data["job_id"])
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="send_linkedin_connection_request",
    description="Send connection request.",
    action_sets=["linkedin"],
    input_schema={
        "invitee_profile_urn": {"type": "string", "description": "Profile URN.", "example": "urn:li:person:123"},
        "message": {"type": "string", "description": "Message.", "example": "Hi"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def send_linkedin_connection_request(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        result = client.send_connection_request(
            input_data["invitee_profile_urn"], message=input_data.get("message")
        )
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="get_linkedin_sent_invitations",
    description="Get sent invitations.",
    action_sets=["linkedin"],
    input_schema={"count": {"type": "integer", "description": "Count.", "example": 50}},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_linkedin_sent_invitations(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        result = client.get_sent_invitations(count=input_data.get("count", 50))
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="get_linkedin_received_invitations",
    description="Get received invitations.",
    action_sets=["linkedin"],
    input_schema={"count": {"type": "integer", "description": "Count.", "example": 50}},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_linkedin_received_invitations(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        result = client.get_received_invitations(count=input_data.get("count", 50))
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="respond_to_linkedin_invitation",
    description="Respond to invitation.",
    action_sets=["linkedin"],
    input_schema={
        "invitation_urn": {"type": "string", "description": "Invitation URN.", "example": "urn:li:invitation:123"},
        "action": {"type": "string", "description": "accept/ignore.", "example": "accept"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def respond_to_linkedin_invitation(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        result = client.respond_to_invitation(input_data["invitation_urn"], input_data["action"])
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="like_linkedin_post",
    description="Like a post.",
    action_sets=["linkedin"],
    input_schema={"post_urn": {"type": "string", "description": "Post URN.", "example": "urn:li:share:123"}},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def like_linkedin_post(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        cred = client._load()
        person_urn = f"urn:li:person:{cred.linkedin_id}" if cred.linkedin_id else f"urn:li:person:{cred.user_id}"
        result = client.like_post(person_urn, input_data["post_urn"])
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="unlike_linkedin_post",
    description="Unlike a post.",
    action_sets=["linkedin"],
    input_schema={"post_urn": {"type": "string", "description": "Post URN.", "example": "urn:li:share:123"}},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def unlike_linkedin_post(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        cred = client._load()
        person_urn = f"urn:li:person:{cred.linkedin_id}" if cred.linkedin_id else f"urn:li:person:{cred.user_id}"
        result = client.unlike_post(person_urn, input_data["post_urn"])
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="get_linkedin_post_likes",
    description="Get post likes.",
    action_sets=["linkedin"],
    input_schema={"post_urn": {"type": "string", "description": "Post URN.", "example": "urn:li:share:123"}},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_linkedin_post_likes(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        result = client.get_post_reactions(input_data["post_urn"])
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="comment_on_linkedin_post",
    description="Comment on a post.",
    action_sets=["linkedin"],
    input_schema={
        "post_urn": {"type": "string", "description": "Post URN.", "example": "urn:li:share:123"},
        "text": {"type": "string", "description": "Comment text.", "example": "Great post!"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def comment_on_linkedin_post(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        cred = client._load()
        person_urn = f"urn:li:person:{cred.linkedin_id}" if cred.linkedin_id else f"urn:li:person:{cred.user_id}"
        result = client.comment_on_post(person_urn, input_data["post_urn"], input_data["text"])
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="get_linkedin_post_comments",
    description="Get post comments.",
    action_sets=["linkedin"],
    input_schema={"post_urn": {"type": "string", "description": "Post URN.", "example": "urn:li:share:123"}},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_linkedin_post_comments(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        result = client.get_post_comments(input_data["post_urn"])
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="delete_linkedin_comment",
    description="Delete a comment.",
    action_sets=["linkedin"],
    input_schema={
        "post_urn": {"type": "string", "description": "Post URN.", "example": "urn:li:share:123"},
        "comment_urn": {"type": "string", "description": "Comment URN.", "example": "urn:li:comment:123"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def delete_linkedin_comment(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        cred = client._load()
        person_urn = f"urn:li:person:{cred.linkedin_id}" if cred.linkedin_id else f"urn:li:person:{cred.user_id}"
        result = client.delete_comment(person_urn, input_data["post_urn"], input_data["comment_urn"])
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="get_my_linkedin_posts",
    description="Get my posts.",
    action_sets=["linkedin"],
    input_schema={"count": {"type": "integer", "description": "Count.", "example": 50}},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_my_linkedin_posts(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        cred = client._load()
        person_urn = f"urn:li:person:{cred.linkedin_id}" if cred.linkedin_id else f"urn:li:person:{cred.user_id}"
        result = client.get_posts_by_author(person_urn, count=input_data.get("count", 50))
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="get_linkedin_organization_posts",
    description="Get organization posts.",
    action_sets=["linkedin"],
    input_schema={"organization_urn": {"type": "string", "description": "Org URN.", "example": "urn:li:organization:123"}},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_linkedin_organization_posts(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        result = client.get_posts_by_author(input_data["organization_urn"])
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="get_linkedin_post",
    description="Get a post.",
    action_sets=["linkedin"],
    input_schema={"post_urn": {"type": "string", "description": "Post URN.", "example": "urn:li:share:123"}},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_linkedin_post(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        result = client.get_post(input_data["post_urn"])
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="reshare_linkedin_post",
    description="Reshare a post.",
    action_sets=["linkedin"],
    input_schema={
        "original_post_urn": {"type": "string", "description": "Original Post URN.", "example": "urn:li:share:123"},
        "commentary": {"type": "string", "description": "Commentary.", "example": "Interesting!"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def reshare_linkedin_post(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        cred = client._load()
        person_urn = f"urn:li:person:{cred.linkedin_id}" if cred.linkedin_id else f"urn:li:person:{cred.user_id}"
        result = client.reshare_post(
            person_urn, input_data["original_post_urn"], commentary=input_data.get("commentary", "")
        )
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="search_linkedin_companies",
    description="Search companies.",
    action_sets=["linkedin"],
    input_schema={"keywords": {"type": "string", "description": "Keywords.", "example": "tech"}},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def search_linkedin_companies(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        result = client.search_companies(input_data["keywords"])
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="lookup_linkedin_company",
    description="Lookup company by vanity name.",
    action_sets=["linkedin"],
    input_schema={"vanity_name": {"type": "string", "description": "Vanity name.", "example": "microsoft"}},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def lookup_linkedin_company(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        result = client.get_company_by_vanity_name(input_data["vanity_name"])
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="get_linkedin_person",
    description="Get person profile by ID.",
    action_sets=["linkedin"],
    input_schema={"person_id": {"type": "string", "description": "Person ID.", "example": "123"}},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_linkedin_person(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        result = client.get_person(input_data["person_id"])
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="get_linkedin_conversations",
    description="Get conversations.",
    action_sets=["linkedin"],
    input_schema={"count": {"type": "integer", "description": "Count.", "example": 20}},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_linkedin_conversations(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        result = client.get_conversations(count=input_data.get("count", 20))
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="get_linkedin_post_analytics",
    description="Get post analytics.",
    action_sets=["linkedin"],
    input_schema={"post_urn": {"type": "string", "description": "Post URN.", "example": "urn:li:share:123"}},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_linkedin_post_analytics(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        result = client.get_post_analytics([input_data["post_urn"]])
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="follow_linkedin_organization",
    description="Follow organization.",
    action_sets=["linkedin"],
    input_schema={"organization_urn": {"type": "string", "description": "Org URN.", "example": "urn:li:organization:123"}},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def follow_linkedin_organization(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        cred = client._load()
        person_urn = f"urn:li:person:{cred.linkedin_id}" if cred.linkedin_id else f"urn:li:person:{cred.user_id}"
        result = client.follow_organization(person_urn, input_data["organization_urn"])
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="unfollow_linkedin_organization",
    description="Unfollow organization.",
    action_sets=["linkedin"],
    input_schema={"organization_urn": {"type": "string", "description": "Org URN.", "example": "urn:li:organization:123"}},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def unfollow_linkedin_organization(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.linkedin import LinkedInClient
        client = LinkedInClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No LinkedIn credential. Use /linkedin login first."}
        cred = client._load()
        person_urn = f"urn:li:person:{cred.linkedin_id}" if cred.linkedin_id else f"urn:li:person:{cred.user_id}"
        result = client.unfollow_organization(person_urn, input_data["organization_urn"])
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}
