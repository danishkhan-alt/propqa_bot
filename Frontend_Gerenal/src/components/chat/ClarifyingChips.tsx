import { useMemo, useState, type FormEvent } from "react";
import {
  Questionnaire,
  QuestionnaireActions,
  QuestionnaireChoice,
  QuestionnaireChoices,
  QuestionnaireError,
  QuestionnaireItem,
  QuestionnaireNext,
  QuestionnairePrevious,
  QuestionnaireProgress,
  QuestionnaireSubmit,
  QuestionnaireTitle,
} from "@/components/ui/questionnaire";

export interface ChipOption {
  id: string;
  label: string;
}

export interface ClarifyingQuestion {
  id: string;
  label: string;
  type: "single_select" | "multi_select";
  options: ChipOption[];
}

interface ClarifyingChipsProps {
  questions: ClarifyingQuestion[];
  ctaLabel: string;
  onSubmit: (answers: Record<string, string>) => void;
}

export function ClarifyingChips({ questions, ctaLabel, onSubmit }: ClarifyingChipsProps) {
  const [submitted, setSubmitted] = useState(false);
  const items = useMemo(
    () =>
      questions.map((question) => ({
        name: question.id,
        required: true,
        multiple: question.type === "multi_select",
        prompt: question.label,
        choices: question.options.map((option) => ({
          value: option.id,
          label: option.label,
        })),
      })),
    [questions],
  );

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitted) return;
    const data = new FormData(event.currentTarget);
    const answers: Record<string, string> = {};
    for (const question of questions) {
      const values = data.getAll(question.id).map(String).filter(Boolean);
      if (values.length === 0) continue;
      answers[question.id] = question.type === "multi_select" ? values.join(",") : values[0];
    }
    setSubmitted(true);
    onSubmit(answers);
  }

  if (questions.length === 0) return null;

  return (
    <div className="mt-3 rounded-2xl border border-[#E8ECF3] bg-[#F7F8FA] px-3 py-3">
      <Questionnaire
        items={items}
        shortcuts="letters"
        onSubmit={handleSubmit}
      >
        <QuestionnaireProgress />
        {items.map((question) => (
          <QuestionnaireItem
            key={question.name}
            name={question.name}
            required={question.required}
            multiple={question.multiple}
          >
            <QuestionnaireTitle>{question.prompt}</QuestionnaireTitle>
            <QuestionnaireChoices>
              {question.choices.map((choice) => (
                <QuestionnaireChoice key={choice.value} value={choice.value}>
                  {choice.label}
                </QuestionnaireChoice>
              ))}
            </QuestionnaireChoices>
            <QuestionnaireError />
          </QuestionnaireItem>
        ))}
        <QuestionnaireActions>
          <QuestionnairePrevious />
          <QuestionnaireNext />
          <QuestionnaireSubmit disabled={submitted}>
            {submitted ? "Sent" : ctaLabel}
          </QuestionnaireSubmit>
        </QuestionnaireActions>
      </Questionnaire>
    </div>
  );
}
