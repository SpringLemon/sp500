# GitHub Issues Alert System

This system will notify users when new GitHub issues are created in the repository.

## Features
- Real-time notifications
- Customizable alert settings

## Setup Instructions
1. Go to your repository settings.
2. Navigate to "Webhooks" and add a webhook.
3. Set the Payload URL to your server endpoint.
4. Choose the "Let me select individual events" option and enable the "Issues" event.
5. Save the changes.

## Example
Here’s an example on how to set up a basic listener for receiving GitHub issue events. A simple Node.js server can be implemented as follows:

```javascript
const express = require('express');
const bodyParser = require('body-parser');

const app = express();
app.use(bodyParser.json());

app.post('/webhook', (req, res) => {
  const issues = req.body;
  // Process GitHub issues here
  console.log(issues);
  res.status(200).send('OK');
});

app.listen(3000, () => {
  console.log('Server is running on port 3000');
});
```

This example shows how to log received issue events to the console.