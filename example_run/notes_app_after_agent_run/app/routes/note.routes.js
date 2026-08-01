module.exports = (app) => {
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
}