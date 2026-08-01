"""
demo_mock_script.py
--------------------
A scripted sequence of "model turns" used by MockLLM to demonstrate and
test the agent harness completely offline (no API key / network needed).

This does NOT hardcode "notes app" logic into the agent itself -- the
agent (coding_agent.py) has zero knowledge of what's in this file. This
script only stands in for what a real LLM (e.g. Groq's llama-3.3-70b)
would plausibly do when given the same repo + request, so that the full
explore -> plan -> execute -> summarize loop, tool dispatch, and file
sandboxing can be verified and demoed without live API access.

When you run with a real API key (`python run_agent.py --repo-path ...`
without --mock), the LLM decides everything itself from scratch.
"""

from __future__ import annotations


NEW_MODEL = """const mongoose = require('mongoose');

const NoteSchema = mongoose.Schema({
    title: String,
    content: String,
    tags: {
        type: [String],
        default: []
    }
}, {
    timestamps: true
});

module.exports = mongoose.model('Note', NoteSchema);"""


NEW_ROUTES = """module.exports = (app) => {
    const notes = require('../controllers/note.controller.js');

    // Create a new Note
    app.post('/notes', notes.create);

    // Search notes by keyword (title/content) and/or tag.
    // NOTE: this must be registered BEFORE '/notes/:noteId' below,
    // otherwise Express would treat "search" as a noteId.
    app.get('/notes/search', notes.search);

    // Retrieve all Notes
    app.get('/notes', notes.findAll);

    // Retrieve a single Note with noteId
    app.get('/notes/:noteId', notes.findOne);

    // Update a Note with noteId
    app.put('/notes/:noteId', notes.update);

    // Delete a Note with noteId
    app.delete('/notes/:noteId', notes.delete);
}"""


NEW_CONTROLLER = """const Note = require('../models/note.model.js');

// Create and Save a new Note
exports.create = (req, res) => {
    // Validate request
    if(!req.body.content) {
        return res.status(400).send({
            message: "Note content can not be empty"
        });
    }

    // Create a Note
    const note = new Note({
        title: req.body.title || "Untitled Note",
        content: req.body.content,
        tags: Array.isArray(req.body.tags) ? req.body.tags : []
    });

    // Save Note in the database
    note.save()
    .then(data => {
        res.send(data);
    }).catch(err => {
        res.status(500).send({
            message: err.message || "Some error occurred while creating the Note."
        });
    });
};

// Retrieve and return all notes from the database.
exports.findAll = (req, res) => {
    Note.find()
    .then(notes => {
        res.send(notes);
    }).catch(err => {
        res.status(500).send({
            message: err.message || "Some error occurred while retrieving notes."
        });
    });
};

// Find a single note with a noteId
exports.findOne = (req, res) => {
    Note.findById(req.params.noteId)
    .then(note => {
        if(!note) {
            return res.status(404).send({
                message: "Note not found with id " + req.params.noteId
            });
        }
        res.send(note);
    }).catch(err => {
        if(err.kind === 'ObjectId') {
            return res.status(404).send({
                message: "Note not found with id " + req.params.noteId
            });
        }
        return res.status(500).send({
            message: "Error retrieving note with id " + req.params.noteId
        });
    });
};

// Search notes by keyword (matches title or content) and/or tag.
// Examples:
//   GET /notes/search?q=meeting
//   GET /notes/search?tag=work
//   GET /notes/search?q=meeting&tag=work
exports.search = (req, res) => {
    const { q, tag } = req.query;
    const conditions = [];

    if (q) {
        const regex = new RegExp(q, 'i');
        conditions.push({ $or: [{ title: regex }, { content: regex }] });
    }

    if (tag) {
        conditions.push({ tags: tag });
    }

    const query = conditions.length > 0 ? { $and: conditions } : {};

    Note.find(query)
    .then(notes => {
        res.send(notes);
    }).catch(err => {
        res.status(500).send({
            message: err.message || "Some error occurred while searching notes."
        });
    });
};

// Update a note identified by the noteId in the request
exports.update = (req, res) => {
    // Validate Request
    if(!req.body.content) {
        return res.status(400).send({
            message: "Note content can not be empty"
        });
    }

    const updatedFields = {
        title: req.body.title || "Untitled Note",
        content: req.body.content
    };
    if (Array.isArray(req.body.tags)) {
        updatedFields.tags = req.body.tags;
    }

    // Find note and update it with the request body
    Note.findByIdAndUpdate(req.params.noteId, updatedFields, {new: true})
    .then(note => {
        if(!note) {
            return res.status(404).send({
                message: "Note not found with id " + req.params.noteId
            });
        }
        res.send(note);
    }).catch(err => {
        if(err.kind === 'ObjectId') {
            return res.status(404).send({
                message: "Note not found with id " + req.params.noteId
            });
        }
        return res.status(500).send({
            message: "Error updating note with id " + req.params.noteId
        });
    });
};

// Delete a note with the specified noteId in the request
exports.delete = (req, res) => {
    Note.findByIdAndRemove(req.params.noteId)
    .then(note => {
        if(!note) {
            return res.status(404).send({
                message: "Note not found with id " + req.params.noteId
            });
        }
        res.send({message: "Note deleted successfully!"});
    }).catch(err => {
        if(err.kind === 'ObjectId' || err.name === 'NotFound') {
            return res.status(404).send({
                message: "Note not found with id " + req.params.noteId
            });
        }
        return res.status(500).send({
            message: "Could not delete note with id " + req.params.noteId
        });
    });
};"""


def build_notes_app_mock_script() -> list[dict]:
    """Scripted turns for MockLLM, mirroring what a real model does via tools.py's schema."""
    return [
        # 1. Explore: look at the repo root.
        {"type": "tool_calls", "calls": [{"name": "list_directory", "arguments": {"path": "."}}]},
        # 2. Explore: read the model.
        {"type": "tool_calls", "calls": [{"name": "read_file", "arguments": {"path": "app/models/note.model.js"}}]},
        # 3. Explore: read the routes.
        {"type": "tool_calls", "calls": [{"name": "read_file", "arguments": {"path": "app/routes/note.routes.js"}}]},
        # 4. Explore: read the controller.
        {"type": "tool_calls", "calls": [{"name": "read_file", "arguments": {"path": "app/controllers/note.controller.js"}}]},
        # 5. Plan (plain text, no tool calls).
        {
            "type": "text",
            "content": (
                "PLAN:\n"
                "- The app is an Express + MongoDB (Mongoose) REST API for notes. "
                "Notes currently only have `title` and `content`; there is no way "
                "to categorize or search notes.\n"
                "- I will add a `tags` array field to the Note model, so notes can "
                "be organized into free-form categories (e.g. 'work', 'personal').\n"
                "- I will add a new `search` controller function that filters notes "
                "by a text keyword (matched against title/content) and/or a tag, "
                "via query params.\n"
                "- I will add a new route `GET /notes/search`, registered BEFORE "
                "`GET /notes/:noteId` so Express doesn't mistake 'search' for a "
                "note id.\n"
                "- I will update `create` and `update` in the controller to accept "
                "an optional `tags` array in the request body.\n"
                "- Files to modify: app/models/note.model.js, "
                "app/routes/note.routes.js, app/controllers/note.controller.js.\n"
                "- No existing endpoints, fields, or behavior will be removed; "
                "this is purely additive."
            ),
        },
        # 6. Execute: write the model.
        {"type": "tool_calls", "calls": [{"name": "write_file", "arguments": {"path": "app/models/note.model.js", "content": NEW_MODEL}}]},
        # 7. Execute: write the routes.
        {"type": "tool_calls", "calls": [{"name": "write_file", "arguments": {"path": "app/routes/note.routes.js", "content": NEW_ROUTES}}]},
        # 8. Execute: write the controller.
        {"type": "tool_calls", "calls": [{"name": "write_file", "arguments": {"path": "app/controllers/note.controller.js", "content": NEW_CONTROLLER}}]},
        # 9. Summarize (plain text, no tool calls) -> loop ends.
        {
            "type": "text",
            "content": (
                "SUMMARY:\n"
                "- app/models/note.model.js: added a `tags` array field (default []) to the Note schema.\n"
                "- app/controllers/note.controller.js: `create` and `update` now accept an optional "
                "`tags` array in the request body; added a new `search` handler that filters notes by "
                "a case-insensitive keyword match on title/content (`q`) and/or an exact tag match (`tag`).\n"
                "- app/routes/note.routes.js: added `GET /notes/search`, placed before the "
                "`/notes/:noteId` route so it isn't shadowed by it.\n"
                "- All previous endpoints (POST /notes, GET /notes, GET /notes/:noteId, "
                "PUT /notes/:noteId, DELETE /notes/:noteId) are unchanged and fully backward compatible.\n"
                "- Usage examples:\n"
                "    POST /notes  { \"title\": \"Groceries\", \"content\": \"Milk, eggs\", \"tags\": [\"personal\", \"shopping\"] }\n"
                "    GET  /notes/search?tag=personal\n"
                "    GET  /notes/search?q=milk\n"
                "    GET  /notes/search?q=milk&tag=shopping"
            ),
        },
    ]
