# Interactive Web Application Builder

This is a web-based application that users can build, polish, and host web-based applications. Use FastAPI and sqlite database for the backend. There is a common database for the app across all users. Each user is associated with a sqlite databse. Use react and typescript for the frontend. LLM API will be used as the main production engine. Multiple providers will be used and can be configured by admin in the app setting page.

## Logical design

The application builder should follow the development cycle: product description, product design, implementation plan, phase by phase implementation, verification and improvement, and deployment.

1. The agent should communicate to the user to finalize the product description based on user's query. The output should be a product description in a markdown file.
2. The agent should design the app including the backend and frontend. The output could a static HTML or a markdown file. Users can feedback to the design and the agent will change accordingly.
3. The agent should create a detailed phase by phase implementation plan. The outptu should be a static HTML or a markdown file. By default, each phase should have a ready to share page implemented.
4. The agent should implement one phase each time. The agent could delegate other agetns for fast and focused implementation. After each phaes is completed, user should provide the feedback. The agent will then change accordingly. The users can see the preview of the application and use area picker to select locations that needed change..
5. After its implementation, the agent should review the outcome with the user and get approval from the users unless auto mode has been enabled.
6. The applicaiton will be host as children of the base url such as *base_url/app_id"". There will be one node module for each user for all applications and one virtual python environment for each application.

## UI design

This is a draft idea. The frontend includes: login page, registration page, user management page (admin only), setting page (admin only), configuration page (per user), application builder page, and other pages could be hosted.

For the application builder page, it could contain a chat on the left, and agent working session or preview on the right.

Use your imagination.