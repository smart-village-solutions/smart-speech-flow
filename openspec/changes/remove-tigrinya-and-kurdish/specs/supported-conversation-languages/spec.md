## ADDED Requirements

### Requirement: Removed languages are unsupported throughout SSF

SSF SHALL NOT advertise or accept Tigrinya (`ti`) or Kurdish (`ku`) as supported
conversation, recognition, translation, or speech synthesis languages. SSF
SHALL remove their bundled UI catalogues and speech synthesis registrations.
Model capabilities SHALL NOT implicitly reintroduce either language.

#### Scenario: Language discovery and selection

- **WHEN** a client queries supported languages or opens the language picker
- **THEN** neither `ti` nor `ku` is offered
- **AND** the remaining supported languages remain available

#### Scenario: Explicit request for a removed language

- **WHEN** a client requests conversation activation, recognition, translation,
  or speech synthesis using `ti` or `ku`
- **THEN** SSF rejects the request using the applicable unsupported-language
  response without invoking model inference for that language

#### Scenario: Existing conversation uses a removed language

- **WHEN** a stored conversation uses `ti` or `ku`
- **THEN** the stored conversation and its history are preserved
- **AND** new processing using that language is rejected as unsupported
- **AND** SSF does not silently substitute another conversation language
