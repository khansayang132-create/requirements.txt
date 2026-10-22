package com.taikatranslator.provider;

import com.taikatranslator.retry.ProviderException;

import java.util.List;
import java.util.Optional;

/** The seam every pipeline stage depends on. Tests inject a fake; production injects DeepL. */
public interface Translator {

    record Request(List<String> texts, Optional<String> sourceLang, String targetLang, boolean xmlTags) { }

    record Response(List<String> texts, Optional<String> detectedSourceLang, int retries) { }

    Response translate(Request request) throws ProviderException, InterruptedException;
}
