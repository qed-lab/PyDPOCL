(define (problem get-ark)
  (:domain indiana-jones-ark)
  (:objects indiana nazis army - character
            usa tanis - place
            ark - ark
            gun - weapon)
  (:init (burried ark tanis)
         (alive indiana)
         (at indiana usa)
         (knows-location indiana ark tanis)
         (alive army)
         (at army usa)
         (alive nazis)
         (at nazis tanis)
         (has nazis gun))
  (:goal (and
              (at army usa)
             ; (has army ark)
             ; (not (alive usa))
              ;(not (alive indiana))
              (not (alive nazis))
              )))